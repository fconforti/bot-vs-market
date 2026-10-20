#!/usr/bin/env python3
"""Claude Code PreToolUse hook for the trading sessions.

Blocks (exit 2 + message) anything that could place an order outside guardrails.py,
rewrite history, or push during a dry run. Allow-lists live in bin/run-session.sh;
this is the second net underneath them.
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path


def deny(msg: str) -> None:
    print(f"BLOCKED by .claude/hooks/guard.py: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    if os.environ.get("FINANCE_AGENT") != "1":
        return   # only unattended agent sessions are guarded
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input", {}) or {}
    dry = os.environ.get("FINANCE_DRY_RUN") == "1"
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("FINANCE_ROOT") or os.getcwd()).resolve()

    if tool == "Bash":
        cmd = str(inp.get("command", ""))
        flat = re.sub(r"\s+", " ", cmd)
        if "--confirm" in flat:
            deny("'--confirm' may only be sent by bin/guardrails.py")
        if re.search(r"\bsc\b.*\btrade\b", flat):
            deny("direct 'sc ... trade' calls are forbidden; write a proposal and run bin/guardrails.py execute")
        if re.search(r"\bsc\b.*\b(savings-plans|price-alerts|watchlist|portfolio-groups|login|logout|context select)\b", flat):
            deny("only read-only sc commands are allowed")
        if re.search(r"\b(python3?|uv run python)\b[^|;&]*\.\./", flat):
            deny("no '..' paths in python invocations")
        if re.search(r"\bpython3?\s+-c\b|\buv run python\s+-c\b|\bpython3?\s+-m\b", flat):
            deny("inline python is not allowed; use the scripts in bin/ and strategy/")
        if re.search(r"\b(git)\b.*\b(push\s+(-f|--force)|reset|rebase|filter-branch|checkout\s+--|restore|commit\s+--amend|rm)\b", flat):
            deny("history rewriting git commands are forbidden")
        if re.search(r"\brm\b|\bmv\b|\btruncate\b|>\s*(journal|trades|portfolio|research)/", flat):
            deny("no deleting, moving or shell-redirecting into history directories")
        if dry and re.search(r"guardrails\.py\s+execute\b", flat) and "--dry-run" not in flat:
            deny("FINANCE_DRY_RUN=1: guardrails execute needs --dry-run")
        if dry and re.search(r"\bgit\s+push\b", flat):
            deny("FINANCE_DRY_RUN=1: no push")
        if re.search(r"\b(curl|wget|ssh|scp|nc|sudo|systemctl)\b", flat):
            deny("network/system commands are not part of the session")
        if re.search(r"\b(HALTED|\.env|\.secrets|GH_TOKEN|ANTHROPIC_API_KEY|\.credentials)\b", flat):
            deny("secrets and the kill switch are off limits")
        return

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        raw = str(inp.get("file_path", ""))
        p = Path(raw)
        if not p.is_absolute():
            p = root / p
        try:
            rel = p.resolve().relative_to(root)
        except ValueError:
            deny(f"writes outside the repo are forbidden: {raw}")
        rel_s = rel.as_posix()
        today = os.environ.get("FINANCE_TODAY") or date.today().isoformat()
        append_only_ok = {"research/inbox.md", "MISTAKES.md", "OPERATIONS.md"}
        if rel_s in append_only_ok or "-dryrun" in p.name:
            return
        for d in ("journal/", "trades/", "portfolio/"):
            if rel_s.startswith(d) and p.exists() and not p.name.startswith(today):
                deny(f"{rel_s} is history; never edit past entries, write a new one")
        if rel_s.startswith("research/") and p.exists() and not p.name.startswith(today) and not rel_s.startswith("research/backtests/"):
            deny(f"{rel_s} is history; never edit past research entries")
        if rel_s.startswith("trades/") and p.exists():
            deny(f"{rel_s} already exists; trade files are only rewritten by bin/guardrails.py")
        if rel_s in ("mandate.toml", "MANDATE.md") or rel_s.startswith(("bin/", "finance/", ".claude/", "systemd/", "tests/", ".github/", "web/")):
            deny(f"{rel_s} is infrastructure; the owner edits it, not the agent")
        if os.environ.get("FINANCE_SESSION") != "research" and (rel_s.startswith("strategy/") or rel_s == "STRATEGY.md"):
            deny("the daily session may not change the strategy; put ideas in research/inbox.md")
        if rel_s.startswith("strategy/versions/") and p.exists():
            deny("frozen strategy versions are immutable")
        return


if __name__ == "__main__":
    main()
