#!/usr/bin/env python3
"""Pre-commit hook: history directories are append-only.

Rejects a commit that modifies, renames or deletes an existing tracked file under the
directories listed in mandate.toml [honesty].append_only_dirs (journal/, trades/,
portfolio/, research/), except the listed exceptions (research/inbox.md). New files
are fine. Corrections go in a new entry.

Also rejects removing lines from site/mistakes.md (append-only file).
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def staged_changes() -> list[tuple[str, str]]:
    out = subprocess.run(["git", "diff", "--cached", "--name-status", "-M", "--no-renames"],
                         capture_output=True, text=True, check=True, cwd=ROOT).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0][0], parts[-1]))
    return rows


def main() -> int:
    with (ROOT / "mandate.toml").open("rb") as fh:
        honesty = tomllib.load(fh).get("honesty", {})
    dirs = tuple(d.rstrip("/") + "/" for d in honesty.get("append_only_dirs", []))
    exceptions = set(honesty.get("append_only_exceptions", []))
    problems = []
    for status, path in staged_changes():
        if path in exceptions or "-dryrun" in path:
            continue   # dry-run journals/snapshots are rehearsals and may be re-run
        if path.startswith(dirs) and status in ("M", "D", "R", "T"):
            problems.append(f"{status} {path}")
        if path == "site/mistakes.md" and status in ("M", "D"):
            diff = subprocess.run(["git", "diff", "--cached", "--", path], capture_output=True, text=True, cwd=ROOT).stdout
            removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
            if removed:
                problems.append(f"lines removed from {path}: {len(removed)}")
    if problems:
        print("append-only violation (history is never rewritten; add a new entry instead):")
        for p in problems:
            print("  " + p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
