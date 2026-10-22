"""Thin wrapper around the Scalable Capital CLI (`sc`).

Every call goes through `run()`, which:
- never passes secrets on the command line and never prints the environment;
- parses the JSON envelope {"ok": bool, "command": str, "data" | "error": ...};
- maps the CLI's documented exit codes (10 validation, 20 auth/config, 30 network,
  1 generic) to a single ScError with the code attached.

`SC_BIN` overrides the binary (tests and the logged-out dry run point it at
tests/fake_sc.py, which serves fixtures from `FINANCE_SC_FIXTURES`).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any

EXIT_VALIDATION = 10
EXIT_AUTH = 20
EXIT_NETWORK = 30
EXIT_GENERIC = 1

DEFAULT_TIMEOUT = 90


class ScError(Exception):
    """Any failure talking to `sc`. `exit_code` follows the CLI's documented codes."""

    def __init__(self, message: str, *, exit_code: int = EXIT_GENERIC,
                 error_code: str | None = None, raw: str = "", args: list[str] | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.error_code = error_code
        self.raw = raw
        self.args_used = args or []

    @property
    def is_auth(self) -> bool:
        return self.exit_code == EXIT_AUTH

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "exit_code": self.exit_code,
            "error_code": self.error_code,
            "args": self.args_used,
            "raw": self.raw[:4000],
        }


@dataclass
class ScResult:
    command: str
    data: Any
    raw: str
    args: list[str]


def sc_bin() -> str:
    return os.environ.get("SC_BIN", "sc")


def _safe_env() -> dict[str, str]:
    """Environment for the child process. We pass the parent env through (the CLI
    needs HOME/XDG and SC_CONFIG_DIR) but never log it."""
    return dict(os.environ)


# This machine's Wi-Fi drops requests a few times a day; on 2026-10-22 `sc whoami`
# failed on two calls out of three with network_error/internal_error while the login
# was valid. Calls that cannot place an order are retried on such errors. A confirm
# (`--confirm`) is never retried: a lost response may hide an order that was placed.
TRANSIENT_CODES = {"network_error", "internal_error", "timeout", "service_unavailable"}


def retry_delays() -> list[float]:
    raw = os.environ.get("FINANCE_SC_RETRY_DELAYS", "5,15,30")
    return [float(x) for x in raw.split(",") if x.strip()]


def is_transient(exc: "ScError") -> bool:
    return exc.exit_code == EXIT_NETWORK or (exc.error_code or "") in TRANSIENT_CODES


def run(args: list[str], *, timeout: int = DEFAULT_TIMEOUT) -> ScResult:
    """Run `sc <args> --json` and return the parsed `data`. Raises ScError otherwise.
    Transient failures are retried, except for order confirmations."""
    delays = [] if "--confirm" in args else retry_delays()
    for attempt in range(len(delays) + 1):
        try:
            return _run_once(args, timeout=timeout)
        except ScError as exc:
            if attempt >= len(delays) or not is_transient(exc):
                raise
            time.sleep(delays[attempt])
    raise AssertionError("unreachable")


def _run_once(args: list[str], *, timeout: int) -> ScResult:
    argv = [sc_bin(), *args]
    if "--json" not in argv:
        argv.append("--json")
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=_safe_env(), check=False,
        )
    except FileNotFoundError as exc:
        raise ScError(f"sc binary not found: {argv[0]}", exit_code=EXIT_GENERIC, args=args) from exc
    except subprocess.TimeoutExpired as exc:
        raise ScError(f"sc timed out after {timeout}s", exit_code=EXIT_NETWORK, args=args) from exc

    raw = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    envelope: Any = None
    if raw:
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            envelope = None

    if envelope is None:
        raise ScError(
            f"sc returned no JSON envelope (exit {proc.returncode}): {stderr[:500] or raw[:500]}",
            exit_code=proc.returncode if proc.returncode in (EXIT_VALIDATION, EXIT_AUTH, EXIT_NETWORK) else EXIT_GENERIC,
            raw=raw or stderr, args=args,
        )
    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise ScError("sc JSON is not an envelope with an 'ok' field", raw=raw, args=args)

    if envelope.get("ok") is True and proc.returncode == 0:
        return ScResult(command=str(envelope.get("command", "")), data=envelope.get("data"), raw=raw, args=args)

    err = envelope.get("error") or {}
    code = err.get("code") if isinstance(err, dict) else None
    message = err.get("message") if isinstance(err, dict) else str(err)
    exit_code = proc.returncode if proc.returncode in (EXIT_VALIDATION, EXIT_AUTH, EXIT_NETWORK) else EXIT_GENERIC
    if code in ("auth_or_config_error", "unauthorized", "auth_error") or "login" in str(message).lower():
        exit_code = EXIT_AUTH
    raise ScError(f"sc {' '.join(args[:3])} failed: {code}: {message}", exit_code=exit_code,
                  error_code=code, raw=raw, args=args)


def num(value: Any, default: float | None = None) -> float | None:
    """The CLI emits decimals as strings ("50.5000") or numbers. Normalise."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return default


# --- read-only helpers -------------------------------------------------------

def _payload(data: Any) -> dict:
    """Account-scoped commands (overview, holdings, cash-breakdown, quote,
    transactions) wrap their payload: {account_id, portfolio_id, resolution,
    result: {...}}. chart, security-news and whoami do not. Return the payload."""
    if isinstance(data, dict) and isinstance(data.get("result"), dict) and "resolution" in data:
        return data["result"]
    return data or {}


def whoami() -> dict:
    return _payload(run(["whoami"]).data)


def overview() -> dict:
    return _payload(run(["broker", "overview"]).data)


def holdings() -> dict:
    return _payload(run(["broker", "holdings"]).data)


def cash_breakdown() -> dict:
    return _payload(run(["broker", "cash-breakdown"]).data)


def quote(isin: str) -> dict:
    return _payload(run(["broker", "quote", "--isin", isin]).data)


def chart(isin: str, timeframe: str = "1y") -> dict:
    return _payload(run(["broker", "chart", "--isin", isin, "--timeframe", timeframe]).data)


def transactions(*, statuses: list[str] | None = None, page_size: int = 50, isin: str | None = None) -> dict:
    args = ["broker", "transactions", "--page-size", str(page_size)]
    for s in statuses or []:
        args += ["--status", s]
    if isin:
        args += ["--isin", isin]
    return _payload(run(args).data)


def open_orders() -> list[dict]:
    """Orders that are not yet filled/settled. Uses the transactions status filter,
    the only way the CLI exposes pending orders."""
    data = transactions(statuses=["CREATED", "REQUESTED", "PENDING", "PARTIAL_FILLED", "CANCEL_REQUESTED"])
    return [i for i in data.get("items", []) if i.get("summary_type") == "BrokerSecurityTransactionSummary"]


def security_news(isin: str, locale: str = "en_DE") -> dict:
    return _payload(run(["broker", "security-news", "--isin", isin, "--locale", locale]).data)


# --- order flow (only bin/guardrails.py may call these) ----------------------

def trade_args(side: str, isin: str, *, eur_amount: float | None, quantity: float | None,
               order_type: str, limit_price: float | None, stop_price: float | None,
               venue: str | None, confirm: str | None = None) -> list[str]:
    if side not in ("buy", "sell"):
        raise ValueError(f"bad side {side!r}")
    args = ["broker", "trade", side, "--isin", isin]
    if side == "buy":
        if (eur_amount is None) == (quantity is None):
            raise ValueError("buy needs exactly one of eur_amount or quantity")
        if eur_amount is not None:
            args += ["--amount", f"{eur_amount:.2f}"]
        else:
            args += ["--shares", str(int(quantity))]
    else:
        if quantity is None:
            raise ValueError("sell needs quantity")
        args += ["--shares", f"{quantity:.6f}".rstrip("0").rstrip(".")]
    args += ["--order-type", order_type]
    if limit_price is not None:
        args += ["--limit-price", f"{limit_price:.4f}"]
    if stop_price is not None:
        args += ["--stop-price", f"{stop_price:.4f}"]
    if venue:
        args += ["--venue", venue]
    if confirm:
        args += ["--confirm", confirm]
    return args


def trade_preview(args: list[str]) -> ScResult:
    assert "--confirm" not in args
    return run(args, timeout=120)


def trade_confirm(args: list[str]) -> ScResult:
    assert "--confirm" in args
    return run(args, timeout=120)
