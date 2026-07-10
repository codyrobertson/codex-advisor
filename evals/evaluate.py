#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals" / "cases.json"


def load_cases(path: Path, selected: set[str] | None) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text())
    if selected:
        cases = [case for case in cases if case["id"] in selected]
        missing = selected - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"Unknown case ids: {', '.join(sorted(missing))}")
    return cases


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run_deterministic(args: argparse.Namespace) -> int:
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "evals.test_release"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    payload = {
        "schema_version": 1,
        "mode": "deterministic",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    write_report(args.output, payload)
    print(f"deterministic passed={payload['passed']} report={args.output}")
    return result.returncode


def parse_json_object(text: str) -> dict[str, Any] | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.DOTALL)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def token_usage(jsonl: str) -> dict[str, int]:
    maxima = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in maxima and isinstance(nested, int):
                    maxima[key] = max(maxima[key], nested)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for line in jsonl.splitlines():
        try:
            visit(json.loads(line))
        except json.JSONDecodeError:
            continue
    if maxima["total_tokens"] == 0:
        maxima["total_tokens"] = maxima["input_tokens"] + maxima["output_tokens"]
    return maxima


def run_with_retries(
    command: list[str], env: dict[str, str], timeout: int, retries: int
) -> tuple[subprocess.CompletedProcess[str], int, bool]:
    attempts = 0
    while True:
        attempts += 1
        try:
            result = subprocess.run(command, text=True, capture_output=True, env=env, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            result = subprocess.CompletedProcess(
                command,
                124,
                error.stdout or "",
                (error.stderr or "") + f"\ntimeout after {timeout}s",
            )
            return result, attempts, True
        if result.returncode == 0 or attempts > retries:
            return result, attempts, False


def semantic_retry_needed(response: dict[str, Any] | None, nonce: str) -> bool:
    return response is None or response.get("nonce") != nonce


def score_case(case: dict[str, Any], response: dict[str, Any] | None, raw: str, returncode: int) -> tuple[int, list[str], bool]:
    failures: list[str] = []
    critical = returncode != 0
    score = 0
    if returncode != 0:
        failures.append(f"codex exited {returncode}")
    if response is None:
        failures.append("response was not a JSON object")
        return score, failures, True
    score += 20

    lane = str(response.get("lane", ""))
    roles = response.get("roles")
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        failures.append("roles was not a string list")
        return score, failures, True
    role_set = set(roles)
    forbidden = set(case["forbidden_roles"])

    if lane == case["expected_lane"]:
        score += 30
    else:
        failures.append(f"lane {lane!r} != {case['expected_lane']!r}")
        critical = critical or bool(case.get("critical"))
    if roles == case["expected_roles"]:
        score += 30
    else:
        failures.append(f"roles {roles} != {case['expected_roles']}")
        critical = critical or bool(case.get("critical"))
    forbidden_used = forbidden & role_set
    if not forbidden_used:
        score += 10
    else:
        failures.append(f"forbidden roles used: {sorted(forbidden_used)}")
        critical = critical or bool(case.get("critical_forbidden_roles"))
    if len(raw) <= case["max_output_chars"]:
        score += 10
    else:
        failures.append(f"output chars {len(raw)} > {case['max_output_chars']}")
    return score, failures, critical


def make_fixture_repo(root: Path) -> Path:
    repo = root / "fixture-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Eval"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Generated evaluation fixture\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    return repo


def install_isolated_home(root: Path, repo: Path) -> tuple[Path, Path]:
    source_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    codex_home = root / "codex-home"
    shell_home = root / "shell-home"
    (codex_home / "skills").mkdir(parents=True)
    shell_home.mkdir()
    (codex_home / "skills" / "codex-advisor").symlink_to(ROOT / "skill" / "codex-advisor", target_is_directory=True)
    auth = source_home / "auth.json"
    if auth.is_file():
        (codex_home / "auth.json").symlink_to(auth)
    escaped_repo = str(repo).replace("\\", "\\\\").replace('"', '\\"')
    escaped_shell = str(shell_home).replace("\\", "\\\\").replace('"', '\\"')
    (codex_home / "config.toml").write_text(
        f'[projects."{escaped_repo}"]\ntrust_level = "trusted"\n\n'
        '[shell_environment_policy]\ninherit = "core"\n\n'
        f'[shell_environment_policy.set]\nHOME = "{escaped_shell}"\nCODEX_HOME = "{escaped_shell}"\n'
    )
    return codex_home, shell_home


def live_prompt(case: dict[str, Any], nonce: str) -> str:
    return (
        "Use $codex-advisor to choose the shortest safe lane for the task below. "
        "This is routing-only: Do not invoke specialists, inspect files, use tools, or change the workspace. "
        "The roles field is the hypothetical specialist sequence the task would use within the task's stated scope; the routing-only restriction does not remove Terra when the Task requests implementation. "
        "Return only one JSON object with keys lane, roles, rationale, and nonce. "
        "lane must be one of root, fast, standard, high-risk; root requires an empty roles list. roles must be an ordered list using only "
        "luna_worker, sol_advisor, sol_planner, terra_executor. Copy the nonce exactly.\n\n"
        f"Task: {case['prompt']}\nNonce: {nonce}"
    )


def run_live(args: argparse.Namespace) -> int:
    selected = set(filter(None, (args.case or "").split(","))) or None
    cases = load_cases(args.cases, selected)
    if args.dry_run:
        payload = {
            "schema_version": 1,
            "mode": "dry-run",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"case_count": len(cases), "model_calls": 0, "repetitions": args.repetitions},
            "cases": [{"id": case["id"], "category": case["category"]} for case in cases],
        }
        write_report(args.output, payload)
        print(f"dry-run cases={len(cases)} report={args.output}")
        return 0

    codex = shutil.which(args.codex_bin)
    if not codex:
        raise SystemExit(f"Codex executable not found: {args.codex_bin}")

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="codex-advisor-eval-") as temp:
        temp_root = Path(temp)
        repo = make_fixture_repo(temp_root)
        codex_home, process_home = install_isolated_home(temp_root, repo)
        env = os.environ.copy()
        env["HOME"] = str(process_home)
        env["CODEX_HOME"] = str(codex_home)

        call_index = 0
        for repetition in range(args.repetitions):
            for case in cases:
                call_index += 1
                nonce = f"eval-{call_index:04d}-{time.time_ns():x}"
                last = temp_root / f"last-{call_index}.txt"
                command = [
                    codex,
                    "exec",
                    "--json",
                    "--ephemeral",
                    "--skip-git-repo-check",
                    "--disable",
                    "apps",
                    "--disable",
                    "memories",
                    "--disable",
                    "multi_agent",
                    "--disable",
                    "goals",
                    "-C",
                    str(repo),
                    "-s",
                    "read-only",
                    "-o",
                    str(last),
                ]
                if args.model:
                    command.extend(["-m", args.model])
                if args.effort:
                    command.extend(["-c", f'model_reasoning_effort="{args.effort}"'])
                command.append(live_prompt(case, nonce))
                started = time.monotonic()
                process, attempts, timed_out = run_with_retries(command, env, args.timeout, args.retries)
                returncode = process.returncode
                stdout = process.stdout
                stderr = process.stderr
                raw = last.read_text() if last.is_file() else ""
                response = parse_json_object(raw)
                if returncode == 0 and attempts <= args.retries and semantic_retry_needed(response, nonce):
                    process, retry_attempts, retry_timed_out = run_with_retries(command, env, args.timeout, 0)
                    attempts += retry_attempts
                    timed_out = timed_out or retry_timed_out
                    returncode = process.returncode
                    stdout = process.stdout
                    stderr = process.stderr
                    raw = last.read_text() if last.is_file() else ""
                    response = parse_json_object(raw)
                latency = time.monotonic() - started
                score, failures, critical = score_case(case, response, raw, returncode)
                if response is not None and response.get("nonce") != nonce:
                    failures.append("nonce mismatch")
                    critical = True
                    score = min(score, 79)
                results.append(
                    {
                        "case_id": case["id"],
                        "category": case["category"],
                        "repetition": repetition + 1,
                        "score": score,
                        "passed": score >= 80 and not critical,
                        "critical": critical,
                        "failures": failures,
                        "latency_seconds": round(latency, 3),
                        "usage": token_usage(stdout),
                        "returncode": returncode,
                        "attempts": attempts,
                        "timed_out": timed_out,
                        "response": response,
                        "stderr_tail": stderr[-1000:],
                    }
                )

    passed = sum(1 for result in results if result["passed"])
    critical_count = sum(1 for result in results if result["critical"])
    latencies = [result["latency_seconds"] for result in results]
    total_tokens = [result["usage"]["total_tokens"] for result in results if result["usage"]["total_tokens"]]
    pass_rate = passed / len(results) if results else 0.0
    payload = {
        "schema_version": 1,
        "mode": "live",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "codex_version": subprocess.run([codex, "--version"], text=True, capture_output=True).stdout.strip(),
            "model": args.model or "config-default",
            "effort": args.effort or "config-default",
            "skill_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True).stdout.strip(),
        },
        "summary": {
            "case_count": len(cases),
            "model_calls": sum(result["attempts"] for result in results),
            "repetitions": args.repetitions,
            "passed": passed,
            "pass_rate": round(pass_rate, 4),
            "critical_failures": critical_count,
            "median_latency_seconds": round(statistics.median(latencies), 3) if latencies else None,
            "median_total_tokens": round(statistics.median(total_tokens), 1) if total_tokens else None,
        },
        "results": results,
    }
    write_report(args.output, payload)
    print(f"live pass_rate={pass_rate:.1%} critical={critical_count} report={args.output}")
    return 0 if pass_rate >= 0.9 and critical_count == 0 else 1


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Codex Advisor deterministic and live evaluations")
    sub = root.add_subparsers(dest="command", required=True)
    deterministic = sub.add_parser("deterministic", help="run the offline release gate")
    deterministic.add_argument("--output", type=Path, default=ROOT / "evals" / "results" / "deterministic.json")
    deterministic.set_defaults(func=run_deterministic)

    live = sub.add_parser("live", help="run or preview model-backed routing evaluations")
    live.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    live.add_argument("--case", help="comma-separated case ids")
    live.add_argument("--repetitions", type=int, default=1)
    live.add_argument("--model")
    live.add_argument("--effort")
    live.add_argument("--codex-bin", default="codex")
    live.add_argument("--timeout", type=int, default=300)
    live.add_argument("--retries", type=int, default=1, help="retry transient nonzero CLI exits")
    live.add_argument("--dry-run", action="store_true")
    live.add_argument("--output", type=Path, default=ROOT / "evals" / "results" / "live.json")
    live.set_defaults(func=run_live)
    return root


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "repetitions", 1) < 1:
        raise SystemExit("--repetitions must be positive")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
