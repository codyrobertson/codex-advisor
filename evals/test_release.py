from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from evals.evaluate import score_case, token_usage


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill" / "codex-advisor"


class RepositoryShapeTests(unittest.TestCase):
    def test_public_release_files_exist(self) -> None:
        required = [
            ROOT / "README.md",
            ROOT / "LICENSE",
            ROOT / ".github" / "workflows" / "ci.yml",
            ROOT / "scripts" / "install.sh",
            ROOT / "evals" / "cases.json",
            ROOT / "evals" / "evaluate.py",
            ROOT / "evals" / "fake-bin" / "codex",
            ROOT / "evals" / "baselines" / "live-smoke.json",
            SKILL / "SKILL.md",
            SKILL / "scripts" / "run-role.sh",
            SKILL / "scripts" / "worktree-state.py",
        ]
        self.assertEqual([], [str(path.relative_to(ROOT)) for path in required if not path.is_file()])

    def test_skill_frontmatter_and_size(self) -> None:
        text = (SKILL / "SKILL.md").read_text()
        self.assertRegex(text, r"\A---\nname: codex-advisor\ndescription: Use when ")
        self.assertLessEqual(len(text.split()), 500)

    def test_role_pins_are_exact(self) -> None:
        expected = {
            "sol_advisor.toml": ("gpt-5.6-sol", "xhigh", "read-only"),
            "sol_planner.toml": ("gpt-5.6-sol", "xhigh", "read-only"),
            "luna_worker.toml": ("gpt-5.6-luna", "medium", "read-only"),
            "terra_executor.toml": ("gpt-5.6-terra", "xhigh", "workspace-write"),
        }
        for name, values in expected.items():
            text = (SKILL / "assets" / "agent-configs" / name).read_text()
            self.assertIn(f'model = "{values[0]}"', text)
            self.assertIn(f'model_reasoning_effort = "{values[1]}"', text)
            self.assertIn(f'sandbox_mode = "{values[2]}"', text)

    def test_public_text_has_no_private_paths_or_token_shapes(self) -> None:
        files = [
            path
            for path in ROOT.rglob("*")
            if path.is_file() and ".git" not in path.parts and path.suffix not in {".pyc"}
        ]
        combined = "\n".join(path.read_text(errors="replace") for path in files)
        private_home = os.path.join(os.sep, "Users", "Cody")
        self.assertNotIn(private_home, combined)
        self.assertNotRegex(combined, r"\bgh[opusr]_[A-Za-z0-9_]{20,}\b")
        self.assertNotRegex(combined, r"\bsk-[A-Za-z0-9_-]{20,}\b")

    def test_eval_matrix_has_breadth_and_machine_checkable_oracles(self) -> None:
        cases = json.loads((ROOT / "evals" / "cases.json").read_text())
        self.assertGreaterEqual(len(cases), 12)
        categories = {case["category"] for case in cases}
        self.assertTrue({"routing", "boundaries", "recovery", "token-pressure"} <= categories)
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        for case in cases:
            self.assertIn(case["expected_lane"], {"root", "fast", "standard", "high-risk"})
            self.assertIsInstance(case["expected_roles"], list)
            self.assertIsInstance(case["forbidden_roles"], list)
            self.assertGreaterEqual(len(case["prompt"]), 40)
            self.assertGreater(case["max_output_chars"], 0)

    def test_checked_in_live_smoke_is_sanitized_and_passing(self) -> None:
        baseline = json.loads((ROOT / "evals" / "baselines" / "live-smoke.json").read_text())
        self.assertEqual(1.0, baseline["summary"]["pass_rate"])
        self.assertEqual(3, baseline["summary"]["model_calls"])
        self.assertRegex(baseline["source_commit"], r"\A[0-9a-f]{40}\Z")
        self.assertEqual(
            {"bounded-fix-verified", "unfamiliar-cross-cutting", "security-boundary-change"},
            {result["case_id"] for result in baseline["results"]},
        )
        self.assertTrue(all(result["passed"] and result["score"] == 100 for result in baseline["results"]))
        serialized = json.dumps(baseline)
        self.assertNotIn("nonce", serialized)
        self.assertNotIn("stderr", serialized)


class RunnerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "eval@example.test"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Eval"], cwd=self.repo, check=True)
        (self.repo / "app.txt").write_text("fixture\n")
        subprocess.run(["git", "add", "app.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.repo, check=True)
        self.brief = SKILL / "SKILL.md"
        self.runner = SKILL / "scripts" / "run-role.sh"
        self.fake_bin = ROOT / "evals" / "fake-bin"
        self.assertTrue((self.fake_bin / "codex").is_file(), "fake Codex is required; never fall through to a live CLI")

    def run_role(self, role: str, *, mode: str = "valid", brief: Path | None = None):
        output = self.base / f"{role}.md"
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["EVAL_FAKE_MODE"] = mode
        env["CODEX_HOME"] = str(self.base / "source-codex-home")
        (self.base / "source-codex-home").mkdir(exist_ok=True)
        result = subprocess.run(
            [str(self.runner), role, str(self.repo), str(brief or self.brief), str(output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        return result, output

    def test_all_roles_accept_valid_contracts(self) -> None:
        terra = self.base / "terra.md"
        terra.write_text(
            "## Plan contract\nApproved.\n\n## This slice\nNo-op.\n\n"
            "## Owned paths\n- None\n\n## Test-first signal\nGap check.\n\n"
            "## Acceptance criteria\nReport.\n\n## Stop conditions\nBefore writes.\n"
        )
        briefs = {"terra-executor": terra}
        for role in ("sol-advisor", "sol-planner", "luna-worker", "terra-executor"):
            result, output = self.run_role(role, brief=briefs.get(role))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(output.is_file())

    def test_invalid_and_failed_outputs_are_never_promoted(self) -> None:
        for mode, expected_suffix in (("malformed", ".invalid"), ("nonzero", ".failed")):
            result, output = self.run_role("luna-worker", mode=mode)
            self.assertNotEqual(0, result.returncode)
            self.assertFalse(output.exists())
            self.assertTrue(Path(f"{output}{expected_suffix}").exists())

    def test_luna_semantic_and_budget_violations_are_rejected(self) -> None:
        modes = ("badfingerprint", "repo-mutated", "luna-nine", "luna-four-reads", "luna-no-path")
        for mode in modes:
            with self.subTest(mode=mode):
                result, output = self.run_role("luna-worker", mode=mode)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(output.exists())
                self.assertTrue(Path(f"{output}.invalid").exists())

    def test_role_specific_semantic_violations_are_rejected(self) -> None:
        for role, mode in (
            ("sol-advisor", "advisor-bad-risk"),
            ("sol-planner", "planner-no-rollback"),
        ):
            with self.subTest(role=role, mode=mode):
                result, output = self.run_role(role, mode=mode)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(output.exists())
                self.assertTrue(Path(f"{output}.invalid").exists())

    def test_oversized_or_extra_heading_output_is_rejected(self) -> None:
        for role, mode in (("sol-advisor", "oversize"), ("sol-advisor", "extra-heading")):
            with self.subTest(mode=mode):
                result, output = self.run_role(role, mode=mode)
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(output.exists())
                self.assertTrue(Path(f"{output}.invalid").exists())

    def test_invalid_run_does_not_clobber_prior_accepted_output(self) -> None:
        accepted = self.base / "luna-worker.md"
        accepted.write_text("accepted result\n")
        result, output = self.run_role("luna-worker", mode="malformed")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("accepted result\n", output.read_text())

    def test_single_line_brief_rejection_is_accepted(self) -> None:
        result, output = self.run_role("luna-worker", mode="brief-rejected")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertRegex(output.read_text(), r"\ABRIEFING_REJECTED: .+")

    def test_unavailable_model_fails_before_role_execution(self) -> None:
        result, output = self.run_role("luna-worker", mode="unavailable-model")
        self.assertEqual(69, result.returncode)
        self.assertFalse(output.exists())
        self.assertIn("model pin is unavailable", result.stderr)

    def test_timeout_is_bounded_and_not_promoted(self) -> None:
        output = self.base / "timeout.md"
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["EVAL_FAKE_MODE"] = "slow"
        env["CODEX_ADVISOR_TIMEOUT_SECONDS"] = "1"
        result = subprocess.run(
            [str(self.runner), "luna-worker", str(self.repo), str(self.brief), str(output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=5,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("timed out", result.stderr)
        self.assertFalse(output.exists())

    def test_isolation_links_auth_but_does_not_import_personal_instructions(self) -> None:
        source_home = self.base / "source-codex-home"
        source_home.mkdir(exist_ok=True)
        (source_home / "auth.json").write_text('{"test": true}\n')
        (source_home / "AGENTS.md").write_text("private instructions\n")
        (source_home / "rules").mkdir()
        log = self.base / "fake.log"
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["CODEX_HOME"] = str(source_home)
        env["EVAL_FAKE_LOG"] = str(log)
        output = self.base / "isolation.md"
        result = subprocess.run(
            [str(self.runner), "luna-worker", str(self.repo), str(self.brief), str(output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        evidence = log.read_text()
        self.assertIn("auth_kind=symlink", evidence)
        self.assertIn("personal_agents=no", evidence)
        self.assertIn("personal_rules=no", evidence)

    def test_terra_rejects_out_of_scope_mutation(self) -> None:
        terra = self.base / "owned.md"
        terra.write_text(
            "## Plan contract\nApproved.\n\n## This slice\nEdit one file.\n\n"
            "## Owned paths\n- allowed.txt\n\n## Test-first signal\nGap.\n\n"
            "## Acceptance criteria\nAllowed file only.\n\n## Stop conditions\nOutside write.\n"
        )
        result, output = self.run_role("terra-executor", mode="terra-outside", brief=terra)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(output.exists())
        self.assertIn("outside owned paths", result.stderr)
        self.assertTrue((self.repo / "outside.txt").exists(), "runner must report, not destroy, unexpected work")

    def test_terra_accepts_mutation_inside_owned_path(self) -> None:
        terra = self.base / "owned-allowed.md"
        terra.write_text(
            "## Plan contract\nApproved.\n\n## This slice\nEdit one file.\n\n"
            "## Owned paths\n- allowed.txt\n\n## Test-first signal\nGap.\n\n"
            "## Acceptance criteria\nAllowed file only.\n\n## Stop conditions\nOutside write.\n"
        )
        result, output = self.run_role("terra-executor", mode="terra-allowed", brief=terra)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(output.exists())
        self.assertEqual("allowed\n", (self.repo / "allowed.txt").read_text())

    def test_exact_model_effort_sandbox_and_feature_flags_reach_codex(self) -> None:
        log = self.base / "argv.log"
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["CODEX_HOME"] = str(self.base / "source-codex-home")
        env["EVAL_FAKE_LOG"] = str(log)
        (self.base / "source-codex-home").mkdir(exist_ok=True)
        output = self.base / "argv.md"
        result = subprocess.run(
            [str(self.runner), "luna-worker", str(self.repo), str(self.brief), str(output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        evidence = log.read_text()
        for expected in (
            "model=gpt-5.6-luna",
            "effort=medium",
            "sandbox=read-only",
            "disable=apps,memories,multi_agent,goals",
        ):
            self.assertIn(expected, evidence)

    def test_promoted_output_permissions_are_private(self) -> None:
        result, output = self.run_role("luna-worker")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0o600, output.stat().st_mode & 0o777)

    def test_outputs_inside_repository_do_not_self_invalidate(self) -> None:
        output_dir = self.repo / ".codex" / "advisor" / "eval"
        output_dir.mkdir(parents=True)
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["CODEX_HOME"] = str(self.base / "source-codex-home")
        luna_output = output_dir / "evidence.md"
        luna = subprocess.run(
            [str(self.runner), "luna-worker", str(self.repo), str(self.brief), str(luna_output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(0, luna.returncode, luna.stderr)
        self.assertTrue(luna_output.is_file())

        terra_brief = self.base / "terra-in-repo.md"
        terra_brief.write_text(
            "## Plan contract\nApproved.\n\n## This slice\nNo-op.\n\n"
            "## Owned paths\n- None\n\n## Test-first signal\nGap.\n\n"
            "## Acceptance criteria\nReport.\n\n## Stop conditions\nBefore writes.\n"
        )
        terra_output = output_dir / "slice.md"
        terra = subprocess.run(
            [str(self.runner), "terra-executor", str(self.repo), str(terra_brief), str(terra_output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=15,
        )
        self.assertEqual(0, terra.returncode, terra.stderr)
        self.assertTrue(terra_output.is_file())

    def test_in_repository_terra_timeout_reports_timeout_not_scope_violation(self) -> None:
        output_dir = self.repo / ".codex" / "advisor" / "timeout"
        output_dir.mkdir(parents=True)
        terra_brief = self.base / "terra-timeout.md"
        terra_brief.write_text(
            "## Plan contract\nApproved.\n\n## This slice\nNo-op.\n\n"
            "## Owned paths\n- None\n\n## Test-first signal\nGap.\n\n"
            "## Acceptance criteria\nReport.\n\n## Stop conditions\nBefore writes.\n"
        )
        output = output_dir / "slice.md"
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["EVAL_FAKE_MODE"] = "slow"
        env["CODEX_ADVISOR_TIMEOUT_SECONDS"] = "1"
        result = subprocess.run(
            [str(self.runner), "terra-executor", str(self.repo), str(terra_brief), str(output)],
            text=True,
            capture_output=True,
            env=env,
            timeout=5,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("timed out", result.stderr)
        self.assertNotIn("outside owned paths", result.stderr)
        self.assertFalse(Path(f"{output}.scope.json").exists())

    def test_submodule_worktree_changes_are_detected_by_scope_verifier(self) -> None:
        child = self.base / "child"
        child.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=child, check=True)
        subprocess.run(["git", "config", "user.email", "eval@example.test"], cwd=child, check=True)
        subprocess.run(["git", "config", "user.name", "Eval"], cwd=child, check=True)
        (child / "nested.txt").write_text("before\n")
        subprocess.run(["git", "add", "nested.txt"], cwd=child, check=True)
        subprocess.run(["git", "commit", "-qm", "child"], cwd=child, check=True)
        subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "vendor/child"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(["git", "commit", "-qam", "add submodule"], cwd=self.repo, check=True)
        helper = SKILL / "scripts" / "worktree-state.py"
        before = self.base / "submodule-before.json"
        subprocess.run(["python3", str(helper), "snapshot", str(self.repo), str(before)], check=True)
        (self.repo / "vendor" / "child" / "nested.txt").write_text("after\n")
        check = subprocess.run(
            ["python3", str(helper), "check", str(self.repo), str(before), "allowed.txt"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(3, check.returncode)
        self.assertIn("vendor/child", check.stdout)

    def test_invalid_timeout_and_terra_brief_fail_before_launch(self) -> None:
        env = os.environ.copy()
        env["PATH"] = f"{self.fake_bin}:{env['PATH']}"
        env["CODEX_ADVISOR_TIMEOUT_SECONDS"] = "zero"
        output = self.base / "bad-timeout.md"
        timeout_result = subprocess.run(
            [str(self.runner), "luna-worker", str(self.repo), str(self.brief), str(output)],
            text=True,
            capture_output=True,
            env=env,
        )
        self.assertEqual(65, timeout_result.returncode)
        self.assertFalse(output.exists())

        bad_brief = self.base / "bad-terra.md"
        bad_brief.write_text("## Plan contract\nOnly one heading.\n")
        brief_result, brief_output = self.run_role("terra-executor", brief=bad_brief)
        self.assertEqual(65, brief_result.returncode)
        self.assertFalse(brief_output.exists())


class InstallerAndEvalCliTests(unittest.TestCase):
    def test_copy_install_registers_skill_and_four_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "codex-home"
            result = subprocess.run(
                [str(ROOT / "scripts" / "install.sh"), "--codex-home", str(target), "--copy"],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((target / "skills" / "codex-advisor" / "SKILL.md").is_file())
            for role in ("sol_advisor", "sol_planner", "luna_worker", "terra_executor"):
                self.assertTrue((target / "agents" / f"{role}.toml").is_file())

    def test_live_eval_dry_run_is_stable_and_makes_no_model_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "report.json"
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "evals" / "evaluate.py"),
                    "live",
                    "--dry-run",
                    "--output",
                    str(report),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(report.read_text())
            self.assertEqual("dry-run", payload["mode"])
            self.assertGreaterEqual(payload["summary"]["case_count"], 12)
            self.assertEqual(0, payload["summary"]["model_calls"])


class EvalScoringTests(unittest.TestCase):
    def test_role_sequence_is_scored_exactly_not_as_an_unordered_set(self) -> None:
        case = {
            "expected_lane": "standard",
            "expected_roles": ["luna_worker", "sol_planner", "terra_executor"],
            "forbidden_roles": ["sol_advisor"],
            "max_output_chars": 500,
        }
        response = {
            "lane": "standard",
            "roles": ["terra_executor", "sol_planner", "luna_worker"],
            "rationale": "reversed",
        }
        score, failures, critical = score_case(case, response, json.dumps(response), 0)
        self.assertLess(score, 80)
        self.assertTrue(any("roles" in failure for failure in failures))
        self.assertFalse(critical)

    def test_wrong_route_is_critical_for_security_case(self) -> None:
        case = {
            "expected_lane": "high-risk",
            "expected_roles": ["luna_worker", "sol_advisor", "sol_planner", "terra_executor"],
            "forbidden_roles": [],
            "max_output_chars": 500,
            "critical": True,
        }
        response = {"lane": "fast", "roles": ["terra_executor"], "rationale": "rush"}
        score, failures, critical = score_case(case, response, json.dumps(response), 0)
        self.assertLess(score, 80)
        self.assertTrue(failures)
        self.assertTrue(critical)

    def test_token_usage_uses_maxima_not_duplicate_event_sums(self) -> None:
        events = "\n".join(
            [
                json.dumps({"usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}}),
                json.dumps({"usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}}),
            ]
        )
        usage = token_usage(events)
        self.assertEqual(100, usage["input_tokens"])
        self.assertEqual(40, usage["output_tokens"])
        self.assertEqual(140, usage["total_tokens"])


if __name__ == "__main__":
    unittest.main()
