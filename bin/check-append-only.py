#!/usr/bin/env python3
"""Pre-commit hook: history directories are append-only.

Rejects a commit that modifies, renames or deletes an existing tracked file under the
directories listed in mandate.toml [honesty].append_only_dirs (journal/, trades/,
portfolio/, research/), except the listed exceptions (research/inbox.md). New files
are fine. Corrections go in a new entry.

Files dated today (the name starts with today's date, Europe/Rome) may still change on
the same day, so a second session that day can refresh the snapshot and continue the
journal: "never changed after the day they are written". A journal file may only grow,
even on its own day; the earlier version stays in git history either way.

Also rejects removing lines from MISTAKES.md and OPERATIONS.md (append-only files).

Series files listed in [honesty].grow_only_series (portfolio/benchmark.json) are
rewritten daily but checked structurally: every earlier point must survive unchanged,
and the fixed fields (units, start date) never change once set.
"""
from __future__ import annotations

import json
import subprocess
import sys
import os
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def removed_lines(path: str) -> int:
    diff = subprocess.run(["git", "diff", "--cached", "--", path], capture_output=True, text=True, cwd=ROOT).stdout
    return len([l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")])


def _staged_json(path: str, rev: str | None) -> dict | None:
    ref = f"{rev}:{path}" if rev else f":{path}"
    out = subprocess.run(["git", "show", ref], capture_output=True, text=True, cwd=ROOT)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}


def series_grows(old: dict | None, new: dict | None) -> str | None:
    """A series file (the benchmark) is rewritten daily but may only grow: every old
    point stays, in place, with the same values, and the fixed fields (units, start)
    never change once set. Returns the problem, or None."""
    if old is None or new is None:
        return None if old is None else "file removed or unreadable"
    for key in ("isin", "initial_eur", "start_date", "units", "start_close"):
        if old.get(key) is not None and old.get(key) != new.get(key):
            return f"{key} changed from {old.get(key)!r} to {new.get(key)!r}"
    old_s, new_s = old.get("series") or [], new.get("series") or []
    if new_s[:len(old_s)] != old_s:
        return f"earlier points changed or removed ({len(old_s)} before, {len(new_s)} after)"
    return None


def main() -> int:
    today = os.environ.get("FINANCE_TODAY") or datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
    with (ROOT / "mandate.toml").open("rb") as fh:
        honesty = tomllib.load(fh).get("honesty", {})
    dirs = tuple(d.rstrip("/") + "/" for d in honesty.get("append_only_dirs", []))
    exceptions = set(honesty.get("append_only_exceptions", []))
    grow_only = set(honesty.get("grow_only_series", []))
    problems = []
    for status, path in staged_changes():
        if path in grow_only:
            if status != "M":
                problems.append(f"{status} {path} (it may only grow)")
            elif why := series_grows(_staged_json(path, "HEAD"), _staged_json(path, None)):
                problems.append(f"{path}: {why} (it may only grow)")
            continue
        if path in exceptions or "-dryrun" in path:
            continue   # dry-run journals/snapshots are rehearsals and may be re-run
        if path.startswith(dirs) and status in ("M", "D", "R", "T"):
            same_day = status == "M" and Path(path).name.startswith(today)
            if not same_day:
                problems.append(f"{status} {path}")
            elif path.startswith("journal/") and (n := removed_lines(path)):
                problems.append(f"lines removed from today's journal {path}: {n} (it may only grow)")
        if path in ("MISTAKES.md", "OPERATIONS.md") and status in ("M", "D"):
            if n := removed_lines(path):
                problems.append(f"lines removed from {path}: {n}")
    if problems:
        print("append-only violation (history is never rewritten; add a new entry instead):")
        for p in problems:
            print("  " + p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
