"""Portfolio snapshots from the broker, plus the benchmark series.

A snapshot is portfolio/YYYY-MM-DD.json. It is written once per day by the daily
session (bin/snapshot.py) and re-written after trades (post-trade snapshot goes to
portfolio/YYYY-MM-DD.post.json so the pre-trade file is never modified).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import paths, sc
from .models import PortfolioState, Position


def _positions_from_holdings(data: dict) -> list[Position]:
    out: list[Position] = []
    for item in data.get("items", []):
        qty = sc.num(item.get("quantity"), 0.0) or 0.0
        if qty <= 0:
            continue
        price = sc.num(item.get("quote_mid_price"))
        value = sc.num(item.get("valuation"))
        if value is None and price is not None:
            value = price * qty
        if price is None and value is not None and qty:
            price = value / qty
        currency = item.get("valuation_currency") or item.get("quote_currency")
        if currency and currency != "EUR":
            raise ValueError(f"holding {item.get('isin')} valued in {currency}, expected EUR")
        out.append(Position(
            isin=str(item.get("isin")),
            name=str(item.get("name") or item.get("isin")),
            quantity=qty,
            price=float(price or 0.0),
            value_eur=float(value or 0.0),
            fifo_price=sc.num(item.get("fifo_price")),
            security_type=item.get("security_type"),
        ))
    return out


def fetch_state(as_of: date | None = None, *, dry_run: bool = False) -> tuple[PortfolioState, dict[str, Any]]:
    """Read overview, holdings and cash from the CLI. Returns the state and the raw
    payloads (stored in the snapshot for auditability)."""
    as_of = as_of or date.today()
    who = sc.whoami()
    ov = sc.overview()
    hold = sc.holdings()
    cash = sc.cash_breakdown()

    positions = _positions_from_holdings(hold)
    cash_balance = sc.num(cash.get("cash_balance"))
    buying_power = sc.num(cash.get("buying_power"), cash_balance)
    if cash_balance is None:
        raise ValueError("cash-breakdown returned no cash_balance; see docs/cli-notes.md")
    nav_total = sc.num((ov.get("valuation") or {}).get("total"))
    securities_value = sum(p.value_eur for p in positions)
    nav = nav_total if nav_total is not None else securities_value + cash_balance
    # Cross-check: the overview NAV should equal cash + securities within rounding.
    recon_gap = abs(nav - (securities_value + cash_balance))
    state = PortfolioState(
        as_of=as_of,
        nav=round(nav, 2),
        cash=round(cash_balance, 2),
        buying_power=round(buying_power if buying_power is not None else cash_balance, 2),
        positions=tuple(positions),
        pending_buy_orders_eur=float(sc.num(cash.get("pending_buy_orders_amount"), 0.0) or 0.0),
        dry_run=dry_run,
    )
    raw = {"whoami": who, "overview": ov, "holdings": hold, "cash_breakdown": cash,
           "reconciliation_gap_eur": round(recon_gap, 2)}
    return state, raw


def snapshot_path(day: date, *, post_trade: bool = False, dry_run: bool = False) -> Path:
    suffix = ("-dryrun" if dry_run else "") + (".post.json" if post_trade else ".json")
    return paths.PORTFOLIO / f"{day.isoformat()}{suffix}"


def write_snapshot(state: PortfolioState, raw: dict[str, Any], *, post_trade: bool = False) -> Path:
    paths.PORTFOLIO.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(state.as_of, post_trade=post_trade, dry_run=state.dry_run)
    payload = state.to_dict()
    payload["taken_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload["post_trade"] = post_trade
    payload["raw"] = raw
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
        fh.write("\n")
    return path


def load_snapshot(path: Path) -> PortfolioState:
    with path.open("r", encoding="utf-8") as fh:
        return PortfolioState.from_dict(json.load(fh))


def list_snapshots(*, include_dry_run: bool = False, include_post: bool = False) -> list[Path]:
    files = sorted(paths.PORTFOLIO.glob("????-??-??*.json"))
    out = []
    for p in files:
        if p.name.endswith(".post.json") and not include_post:
            continue
        if "-dryrun" in p.name and not include_dry_run:
            continue
        out.append(p)
    return out


def latest_state(day: date | None = None, *, dry_run: bool = False) -> PortfolioState | None:
    """Most recent snapshot for `day` (post-trade preferred). Dry runs only ever see
    dry-run snapshots and live runs only live ones. Falls back to the newest file of
    the same kind so callers can report a stale date instead of crashing."""
    day = day or date.today()
    for post in (True, False):
        p = snapshot_path(day, post_trade=post, dry_run=dry_run)
        if p.exists():
            return load_snapshot(p)
    files = [p for p in list_snapshots(include_dry_run=True, include_post=True) if ("-dryrun" in p.name) == dry_run]
    return load_snapshot(files[-1]) if files else None


def equity_curve() -> list[dict[str, Any]]:
    """[{date, nav, cash}] from live snapshots (pre-trade, non dry-run)."""
    out = []
    for p in list_snapshots():
        try:
            s = load_snapshot(p)
        except (OSError, ValueError, KeyError):
            continue
        out.append({"date": s.as_of.isoformat(), "nav": s.nav, "cash": s.cash})
    return out


# --- benchmark -----------------------------------------------------------------

def load_benchmark() -> dict[str, Any]:
    if paths.BENCHMARK.exists():
        with paths.BENCHMARK.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def update_benchmark(*, isin: str, name: str, initial_eur: float, closes: "dict[str, float]",
                     start_date: date | None) -> dict[str, Any]:
    """Keep benchmark.json up to date. Units are fixed on the first live day:
    units = initial_eur / close(start_date). Value on day d = units * close(d).
    `closes` is {iso_date: close_eur} and may include dates before start_date."""
    bench = load_benchmark() or {"isin": isin, "name": name, "initial_eur": initial_eur,
                                 "start_date": None, "units": None, "series": []}
    if start_date is None:
        bench["note"] = "no live run yet; units are fixed on the first live run"
        return bench
    if not bench.get("start_date"):
        start_iso = start_date.isoformat()
        start_close = closes.get(start_iso)
        if start_close is None:
            # first available close on/after start
            later = sorted(d for d in closes if d >= start_iso)
            if not later:
                return bench
            start_iso = later[0]
            start_close = closes[start_iso]
        bench["start_date"] = start_iso
        bench["start_close"] = start_close
        bench["units"] = initial_eur / start_close
    units = bench["units"]
    series = {row["date"]: row for row in bench.get("series", [])}
    for d, c in sorted(closes.items()):
        if d >= bench["start_date"]:
            series[d] = {"date": d, "close": c, "value": round(units * c, 2)}
    bench["series"] = [series[k] for k in sorted(series)]
    bench.pop("note", None)
    return bench


def save_benchmark(bench: dict[str, Any]) -> None:
    paths.PORTFOLIO.mkdir(parents=True, exist_ok=True)
    with paths.BENCHMARK.open("w", encoding="utf-8") as fh:
        json.dump(bench, fh, indent=2)
        fh.write("\n")
