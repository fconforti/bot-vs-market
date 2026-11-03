#!/usr/bin/env python3
"""Is the Scalable CLI logged in and reachable? Used by the runners before a session.

Exit codes: 0 logged in; 3 not logged in (no session, or the broker rejected it);
8 the broker could not be reached, even after retries. Prints one line saying which.

Retries transient errors (finance.sc) for about five minutes by default: on
2026-10-22 a valid login failed two `sc whoami` calls out of three on network errors,
and the runner reported it as an expired login.

Every check records what it saw (finance/login.py). With --remind (the keep-alive)
it also emails the owner once, a day before the login's seven days are up.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FINANCE_SC_RETRY_DELAYS", "10,20,30,60,60,120")

from finance import login, sc  # noqa: E402


def check() -> tuple[int, str]:
    try:
        sc.whoami()
    except sc.ScError as exc:
        if sc.is_transient(exc):
            return 8, f"unreachable: {exc}"
        return 3, f"not logged in: {exc}"
    return 0, "logged in"


def remind(expiry: datetime) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import notify
    notify.send(
        f"Bot vs Market: Scalable login runs out {expiry:%a %d %b %H:%M}, please log in again",
        f"The Scalable CLI login runs out by {expiry:%A %d %B, %H:%M %Z} at the latest\n"
        "(seven days after `sc login`; this estimate errs early).\n\n"
        "Before the next trading session, on the machine, run `sc login`, then `sc whoami --json`.\n"
        "Without it the bot stops trading until you do.\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--remind", action="store_true", help="email a reminder a day before the login runs out")
    args = ap.parse_args(argv)
    rc, msg = check()
    now = datetime.now().astimezone()
    state = login.record(login.load(), {0: "ok", 3: "no_login"}.get(rc, "unreachable"), now)
    exp = login.expires_by(state)
    if rc == 0 and exp:
        msg += f" (runs out by {exp:%Y-%m-%d %H:%M} at the latest)"
    if args.remind and (due := login.due_reminder(state, now)):
        try:
            remind(due)
            state["reminded"] = True
            msg += "; reminder sent"
        except (SystemExit, OSError) as exc:
            msg += f"; reminder NOT sent: {exc}"
    login.save(state)
    print(msg)
    return rc


if __name__ == "__main__":
    sys.exit(main())
