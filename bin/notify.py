#!/usr/bin/env python3
"""Email the owner. Private channel on purpose: the repo and the site are public.

    bin/notify.py --failed-unit finance.service      # used by systemd/finance-alert@.service
    bin/notify.py --subject "..." < body.txt          # anything else
    bin/notify.py --test                              # check the setup

Reads from the environment (systemd: EnvironmentFile=%h/.secrets/finance.env;
interactively: direnv). Store them with `framework secret set finance <KEY>`:

    ALERT_EMAIL     where alerts go, also the Gmail account that sends them
    SMTP_PASSWORD   a Google app password for that account
    SMTP_HOST       optional, default smtp.gmail.com (port 465, TLS)

Standard library only, so it runs with the system Python even if the venv is broken.
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "finance"
SITE = "https://fconforti.github.io/bot-vs-market/"


def _tail(path: Path, lines: int = 60) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return f"({path} not readable)"


def _journalctl(unit: str, lines: int = 40) -> str:
    try:
        out = subprocess.run(["journalctl", "--user", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or out.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(journalctl failed: {exc})"


def failure_message(unit: str) -> tuple[str, str]:
    if "keepalive" in unit:
        return ("Bot vs Market: Scalable login expired, no trading until you log in",
                f"The keep-alive check ({unit}) found no valid Scalable CLI login at "
                f"{datetime.now().astimezone():%Y-%m-%d %H:%M %Z}.\n\n"
                "Fix: on the machine, run `sc login`, then `sc whoami --json`.\n"
                "Logins last at most seven days from `sc login`, whatever the bot does.\n\n"
                f"--- journalctl --user -u {unit} ---\n{_journalctl(unit)}")
    kind = "research" if "research" in unit else "session"
    logs = sorted(STATE_DIR.glob("research-*.log" if kind == "research" else "session-*.log"),
                  key=lambda p: p.stat().st_mtime)
    log = logs[-1] if logs else None
    tail = _tail(log) if log else "(no session log found)"
    if "sc not logged in" in tail:
        subject = "Bot vs Market: Scalable login expired, no trading until you log in"
        action = ("The broker session is missing or expired, so the run stopped before doing anything.\n"
                  "Fix: on the machine, run `sc login`, then `sc whoami --json`.\n"
                  "Nothing else is needed; the next scheduled run picks up from there.")
    else:
        subject = f"Bot vs Market: {unit} failed"
        action = ("The run did not finish cleanly. Whatever it wrote is in the repo (committed unless\n"
                  "the log says the commit was refused). Check "
                  "the log below and the journal before the next run.")
    body = "\n".join([
        f"{unit} failed at {datetime.now().astimezone():%Y-%m-%d %H:%M %Z}.",
        "",
        action,
        "",
        f"Site: {SITE}",
        f"Log: {log or STATE_DIR}",
        "",
        f"--- last lines of {log.name if log else 'log'} ---",
        tail,
        "",
        f"--- journalctl --user -u {unit} ---",
        _journalctl(unit),
    ])
    return subject, body


def send(subject: str, body: str) -> None:
    to = os.environ.get("ALERT_EMAIL")
    password = os.environ.get("SMTP_PASSWORD")
    if not to or not password:
        raise SystemExit("ALERT_EMAIL and SMTP_PASSWORD must be set (framework secret set finance <KEY>)")
    msg = EmailMessage()
    msg["From"] = f"Bot vs Market <{to}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=60) as s:
        s.login(to, password)
        s.send_message(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--failed-unit")
    ap.add_argument("--subject")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--print", action="store_true", help="print the message instead of sending it")
    args = ap.parse_args()
    if args.failed_unit:
        subject, body = failure_message(args.failed_unit)
    elif args.test:
        subject, body = "Bot vs Market: test alert", "If you can read this, failure alerts will reach you."
    elif args.subject:
        subject, body = args.subject, sys.stdin.read()
    else:
        ap.error("one of --failed-unit, --subject, --test")
    if args.print:
        print(f"Subject: {subject}\n\n{body}")
        return 0
    send(subject, body)
    print(f"sent: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
