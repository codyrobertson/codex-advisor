#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


def git_visible_paths(repo: Path, excluded: set[str]) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "-c", "-o", "--exclude-standard"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return sorted(
        item.decode("utf-8", "surrogateescape")
        for item in result.stdout.split(b"\0")
        if item and item.decode("utf-8", "surrogateescape") not in excluded
    )


def file_state(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    mode = stat.S_IMODE(info.st_mode)
    if path.is_symlink():
        target = os.readlink(path)
        digest = hashlib.sha256(target.encode("utf-8", "surrogateescape")).hexdigest()
        return {"kind": "symlink", "mode": mode, "digest": digest}
    if path.is_dir() and (path / ".git").exists():
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, check=False, capture_output=True
        ).stdout
        status_bytes = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=path,
            check=False,
            capture_output=True,
        ).stdout
        digest = hashlib.sha256(head + b"\0" + status_bytes).hexdigest()
        return {"kind": "submodule", "mode": mode, "digest": digest}
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"kind": "file", "mode": mode, "digest": digest.hexdigest()}
    return {"kind": "other", "mode": mode}


def snapshot(repo: Path, excluded: set[str] | None = None) -> dict[str, Any]:
    excluded = {path for path in (excluded or set()) if path}
    return {
        "schema_version": 1,
        "repo": str(repo),
        "excluded": sorted(excluded),
        "files": {relative: file_state(repo / relative) for relative in git_visible_paths(repo, excluded)},
    }


def write_snapshot(repo: Path, output: Path, excluded: set[str]) -> int:
    payload = snapshot(repo, excluded)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n")
    temporary.replace(output)
    return 0


def normalize_owned(raw: str) -> str:
    value = raw.strip().strip("`").rstrip("/")
    if value.lower().rstrip(".") == "none":
        return ""
    path = Path(value)
    if not value or path.is_absolute() or value == "." or ".." in path.parts:
        raise ValueError(f"unsafe owned path: {raw}")
    if any(character in value for character in "*?[]"):
        raise ValueError(f"globs are not allowed in owned paths: {raw}")
    return value


def check(repo: Path, before_path: Path, owned_raw: list[str]) -> int:
    before = json.loads(before_path.read_text())
    after = snapshot(repo, set(before.get("excluded", [])))
    before_files = before.get("files", {})
    after_files = after["files"]
    changed = sorted(
        path
        for path in set(before_files) | set(after_files)
        if before_files.get(path, {"kind": "missing"}) != after_files.get(path, {"kind": "missing"})
    )
    try:
        owned = [value for value in (normalize_owned(raw) for raw in owned_raw) if value]
    except ValueError as error:
        print(json.dumps({"error": str(error), "changed": changed, "outside": changed}))
        return 3
    outside = [path for path in changed if not any(path == root or path.startswith(f"{root}/") for root in owned)]
    print(json.dumps({"changed": changed, "owned": owned, "outside": outside}, sort_keys=True))
    return 3 if outside else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Snapshot and verify Git-visible worktree paths")
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = sub.add_parser("snapshot")
    snapshot_parser.add_argument("repo", type=Path)
    snapshot_parser.add_argument("output", type=Path)
    snapshot_parser.add_argument("--exclude", action="append", default=[])
    check_parser = sub.add_parser("check")
    check_parser.add_argument("repo", type=Path)
    check_parser.add_argument("before", type=Path)
    check_parser.add_argument("owned", nargs="*")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = args.repo.resolve()
    if args.command == "snapshot":
        return write_snapshot(repo, args.output, set(args.exclude))
    return check(repo, args.before, args.owned)


if __name__ == "__main__":
    raise SystemExit(main())
