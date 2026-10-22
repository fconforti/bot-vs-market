#!/usr/bin/env python3
"""Is the Scalable CLI logged in and reachable? Used by the runners before a session.

Exit codes: 0 logged in; 3 not logged in (no session, or the broker rejected it);
8 the broker could not be reached, even after retries. Prints one line saying which.

Retries transient errors (finance.sc) for about five minutes by default: on
2026-10-22 a valid login failed two `sc whoami` calls out of three on network errors,
and the runner reported it as an expired login.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("FINANCE_SC_RETRY_DELAYS", "10,20,30,60,60,120")

from finance import sc  # noqa: E402


def main() -> int:
    try:
        sc.whoami()
    except sc.ScError as exc:
        if sc.is_transient(exc):
            print(f"unreachable: {exc}")
            return 8
        print(f"not logged in: {exc}")
        return 3
    print("logged in")
    return 0


if __name__ == "__main__":
    sys.exit(main())
