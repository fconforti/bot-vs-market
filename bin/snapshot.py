#!/usr/bin/env python3
"""Write portfolio/YYYY-MM-DD.json from the broker account and update the benchmark.

    uv run python bin/snapshot.py              # pre-trade snapshot for today
    uv run python bin/snapshot.py --post-trade # after execution: YYYY-MM-DD.post.json
    uv run python bin/snapshot.py --dry-run    # mark the snapshot as dry-run (fixture or not)

Prints a JSON summary. Exit 3 on CLI/auth errors so the session aborts cleanly.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance import clock, mandate as mandate_mod, portfolio, sc  # noqa: E402


def update_benchmark_from_cache(man: mandate_mod.Mandate) -> dict:
    """Benchmark closes come from the yfinance cache (EUR Xetra listing)."""
    from strategy import data as data_mod

    closes = data_mod.closes_by_isin()
    bench = portfolio.load_benchmark()
    series: dict[str, float] = {}
    if man.benchmark_isin in closes.columns:
        s = closes[man.benchmark_isin].dropna()
        series = {d.strftime("%Y-%m-%d"): float(v) for d, v in s.items()}
    live = portfolio.list_snapshots()
    start = None
    if bench.get("start_date"):
        from datetime import date as _d
        start = _d.fromisoformat(bench["start_date"])
    elif live:
        start = portfolio.load_snapshot(live[0]).as_of
    bench = portfolio.update_benchmark(isin=man.benchmark_isin, name=man.benchmark_name,
                                       initial_eur=man.benchmark_initial_eur, closes=series, start_date=start)
    portfolio.save_benchmark(bench)
    return bench


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--post-trade", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="flag the snapshot as dry-run data")
    ap.add_argument("--no-benchmark", action="store_true")
    args = ap.parse_args(argv)
    today = clock.today()
    try:
        state, raw = portfolio.fetch_state(today, dry_run=args.dry_run)
    except sc.ScError as exc:
        print(json.dumps({"error": "sc", "auth": exc.is_auth, **exc.to_dict()}))
        return 3
    except (ValueError, KeyError) as exc:
        print(json.dumps({"error": "shape", "message": str(exc)}))
        return 3
    path = portfolio.write_snapshot(state, raw, post_trade=args.post_trade)
    out = {"path": str(path), "as_of": state.as_of.isoformat(), "nav": state.nav, "cash": state.cash,
           "buying_power": state.buying_power, "pending_buy_orders_eur": state.pending_buy_orders_eur,
           "positions": [{"isin": p.isin, "name": p.name, "quantity": p.quantity, "price": p.price,
                          "value_eur": p.value_eur, "fifo_price": p.fifo_price,
                          "weight": round(p.value_eur / state.nav, 4) if state.nav else None} for p in state.positions],
           "reconciliation_gap_eur": raw.get("reconciliation_gap_eur"), "dry_run": state.dry_run}
    try:
        open_orders = sc.open_orders()
        out["open_orders"] = [{k: o.get(k) for k in ("id", "isin", "side", "status", "quantity", "amount", "type")} for o in open_orders]
    except sc.ScError as exc:
        out["open_orders_error"] = str(exc)
    if not args.no_benchmark:
        try:
            man = mandate_mod.load()
            bench = update_benchmark_from_cache(man)
            last = bench["series"][-1] if bench.get("series") else None
            out["benchmark"] = {"isin": bench.get("isin"), "start_date": bench.get("start_date"),
                                "last": last, "note": bench.get("note")}
        except Exception as exc:  # noqa: BLE001 - benchmark is informational, never blocks the snapshot
            out["benchmark_error"] = repr(exc)
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
