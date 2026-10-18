#!/usr/bin/env python3
"""Print the facts the daily/research session needs before doing anything.

    uv run python bin/session-info.py

Pure read: today's date, whether the market is open, dry-run / fixture mode, HALTED,
orders already attempted today, strategy version, git head, sc login state.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance import clock, mandate as mandate_mod, paths, sc, trades  # noqa: E402


def main() -> int:
    man = mandate_mod.load()
    today = clock.today()
    try:
        import tomllib
        with (paths.STRATEGY / "params.toml").open("rb") as fh:
            version = tomllib.load(fh).get("version", "?")
    except OSError:
        version = "?"
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=paths.ROOT).stdout.strip()
    except OSError:
        head = "?"
    sc_mode = os.environ.get("FINANCE_SC_MODE", "unknown")
    logged_in = None
    try:
        sc.whoami()
        logged_in = True
    except sc.ScError as exc:
        logged_in = False if exc.is_auth or exc.exit_code == 1 else None
    dry = os.environ.get("FINANCE_DRY_RUN") == "1"
    suffix = "-dryrun" if dry else ""
    out = {
        "date": today.isoformat(),
        "date_override": bool(os.environ.get("FINANCE_TODAY")),   # true when the date was replayed with FINANCE_TODAY
        "weekday": today.strftime("%A"),
        "trading_day": man.is_trading_day(today),
        "holiday": today in man.holidays,
        "session_time": f"{man.session_time} {man.timezone}",
        "dry_run": dry,
        "sc_mode": sc_mode,                      # live | fixture
        "sc_logged_in": logged_in,
        "halted": paths.HALTED.exists(),
        "orders_attempted_today": trades.attempted_today(today),
        "max_orders_per_day": man.limits.max_orders_per_day,
        "strategy_version": version,
        "venue": man.venue,
        "benchmark_isin": man.benchmark_isin,
        "git_head": head,
        "journal_file": f"journal/{today.isoformat()}{suffix}.md",
        "snapshot_file": f"portfolio/{today.isoformat()}{suffix}.json",
        "inbox_file": "research/inbox.md",
        "mistakes_file": "MISTAKES.md",
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
