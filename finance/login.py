"""When was the Scalable CLI last logged in, and when does that login run out?

`sc` does not report a session's age, and a login ends seven days after `sc login`
whatever the bot does (vendor automation guide). On 2026-10-30 one ran out silently
and the 2026-11-02 session, the first day of the monthly exit window, could not
trade. So every broker check records what it saw, and the keep-alive emails a
reminder a day before the seven days are up.

The login time is estimated conservatively: the last check that found no session
(the login happened after it), or, without one, the first successful check minus
the longest gap between keep-alive checks. The reminder may come a few hours early,
never late.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

MAX_AGE = timedelta(days=7)
REMIND_BEFORE = timedelta(days=1)
CHECK_GAP = timedelta(hours=9)   # keep-alive runs at 06, 14 and 22:00, up to 10 min late


def state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "finance" / "login.json"


def load(path: Path | None = None) -> dict:
    try:
        return json.loads((path or state_path()).read_text())
    except (OSError, ValueError):
        return {}


def save(state: dict, path: Path | None = None) -> None:
    p = path or state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n")


def record(state: dict, outcome: str, now: datetime) -> dict:
    """outcome: "ok", "no_login" or "unreachable" (which tells nothing)."""
    state = dict(state)
    if outcome == "ok" and "first_ok" not in state:
        after = state.get("last_no_login")
        state["login_after"] = after or (now - CHECK_GAP).isoformat()
        state["first_ok"] = now.isoformat()
        state["reminded"] = False
    elif outcome == "no_login":
        state = {"last_no_login": now.isoformat()}
    return state


def expires_by(state: dict) -> datetime | None:
    if "login_after" not in state:
        return None
    return datetime.fromisoformat(state["login_after"]) + MAX_AGE


def due_reminder(state: dict, now: datetime) -> datetime | None:
    """The estimated expiry, if a reminder should go out now."""
    exp = expires_by(state)
    if exp is None or state.get("reminded") or now < exp - REMIND_BEFORE:
        return None
    return exp
