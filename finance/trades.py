"""Trade files: one JSON per proposed order under trades/YYYY-MM-DD-NN.json.

Status lifecycle (never goes backwards, files are append-only in git):
  proposed  -> validated by guardrails -> previewed -> executed | rejected | aborted | unknown
  proposed  -> rejected (failed validation, no preview was run)
  proposed  -> dry_run  (preview ran, confirm deliberately skipped)
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import paths

STATUS_PROPOSED = "proposed"
STATUS_EXECUTED = "executed"
STATUS_REJECTED = "rejected"
STATUS_ABORTED = "aborted"
STATUS_UNKNOWN = "unknown"      # confirm was sent, outcome unclear. Never retry.
STATUS_DRY_RUN = "dry_run"
FINAL_STATUSES = {STATUS_EXECUTED, STATUS_REJECTED, STATUS_ABORTED, STATUS_UNKNOWN, STATUS_DRY_RUN}
ATTEMPTED_STATUSES = {STATUS_EXECUTED, STATUS_UNKNOWN, STATUS_ABORTED}   # count against max_orders_per_day

_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{2})\.json$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def trade_dir() -> Path:
    return paths.TRADES


def list_trade_files(day: date | None = None) -> list[Path]:
    files = sorted(p for p in trade_dir().glob("*.json") if _NAME_RE.match(p.name))
    if day is None:
        return files
    prefix = day.isoformat()
    return [p for p in files if p.name.startswith(prefix)]


def next_trade_path(day: date) -> Path:
    existing = list_trade_files(day)
    n = len(existing) + 1
    return trade_dir() / f"{day.isoformat()}-{n:02d}.json"


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: trade file is not a JSON object")
    return data


def load_all() -> list[dict[str, Any]]:
    out = []
    for p in list_trade_files():
        try:
            d = load(p)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        d.setdefault("id", p.stem)
        out.append(d)
    return out


def write(path: Path, data: dict[str, Any]) -> None:
    """Atomic write (tmp file + rename) so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = redact(data)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=False, default=str)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


_SECRET_KEY_RE = re.compile(r"(token|secret|password|cookie|authorization|api[_-]?key)", re.I)


# Query parameters in URLs, e.g. the fund-document links in a preview carry
# `?apiKey=...` (the broker's key for its document provider, 2026-10-19).
_SECRET_PARAM_RE = re.compile(r"([?&][^=&#]*(?:token|secret|password|signature|sig|api[_-]?key)[^=&#]*=)[^&#]*", re.I)


def redact(obj: Any) -> Any:
    """Defensive: we store CLI output raw and publish it, so scrub any key that looks
    like a secret and any secret-looking query parameter inside a URL."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if _SECRET_KEY_RE.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and "://" in obj:
        return _SECRET_PARAM_RE.sub(r"\1[redacted]", obj)
    return obj


def new_proposal(*, day: date, isin: str, side: str, order_type: str = "market",
                 eur_amount: float | None = None, quantity: float | None = None,
                 limit_price: float | None = None, rationale: str = "", name: str = "",
                 strategy_version: str = "", thesis: str = "", dry_run: bool = False) -> Path:
    path = next_trade_path(day)
    data = {
        "id": path.stem,
        "date": day.isoformat(),
        "created_at": now_iso(),
        "isin": isin,
        "name": name,
        "side": side,
        "order_type": order_type,
        "eur_amount": eur_amount,
        "quantity": quantity,
        "limit_price": limit_price,
        "rationale": rationale,
        "thesis": thesis or rationale,
        "strategy_version": strategy_version,
        "status": STATUS_PROPOSED,
        "dry_run": dry_run,
        "checks": [],
        "attempt": None,
        "preview": None,
        "confirm": None,
        "order_id": None,
        "reason": None,
        "fill": None,
    }
    write(path, data)
    return path


def attempted_today(day: date) -> int:
    """Orders that reached the confirm step today (executed, unknown or aborted after
    preview). Rejections before preview do not count; dry runs do not count."""
    n = 0
    for p in list_trade_files(day):
        try:
            d = load(p)
        except (OSError, ValueError, json.JSONDecodeError):
            n += 1   # unreadable file: count it, be conservative
            continue
        if d.get("status") in ATTEMPTED_STATUSES or (d.get("attempt") or {}).get("confirm_sent_at"):
            n += 1
    return n
