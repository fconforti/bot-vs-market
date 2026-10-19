#!/usr/bin/env python3
"""Backtest harness for strategy versions, with the frictions we actually pay.

    uv run python strategy/backtest.py --version current
    uv run python strategy/backtest.py --version v001            # strategy/versions/v001_*.py
    uv run python strategy/backtest.py --version path/to/candidate.py --params path/to/params.toml
    uv run python strategy/backtest.py --version current --start 2016-01-01 --no-chart

Simulation rules (match the live pipeline, not an idealised one):
- One decision per trading day after the close, using only closes up to that day.
- Execution at the same day's close plus half the spread (we trade at 18:15 on EIX
  while the market is still open). Spread: 0.25% ETFs/ETCs, 0.50% stocks, plus the
  0.99% crypto-ETP surcharge. Fee EUR 0.99 per order (Scalable FREE, EIX).
- The same per-day order cap and the mandate's size limits apply; orders the
  guardrails would reject are counted as rejected and not executed.
- Benchmark: EUR 1,000 buy-and-hold of the MSCI World ETF with the same frictions.

Outputs research/backtests/<version>.json and <version>.png. The in-sample /
out-of-sample split is a fixed 70/30 cut of the simulated period. Parameters are
never fitted here, so the split is a sanity check, not a validation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from finance import mandate as mandate_mod  # noqa: E402
from finance.models import MarketData, PortfolioState, Position, ProposedOrder  # noqa: E402
from strategy import data as data_mod  # noqa: E402

SPREAD = {"etf": 0.0025, "etc": 0.0025, "cash": 0.0010, "stock": 0.0050, "crypto": 0.0025}
TRADING_DAYS = 252


@dataclass
class Frictions:
    fee_eur: float = 0.99
    crypto_surcharge: float = 0.0099
    enabled: bool = True

    def exec_price(self, close: float, side: str, itype: str) -> float:
        if not self.enabled:
            return close
        half = SPREAD.get(itype, 0.005) / 2 + (self.crypto_surcharge if itype == "crypto" else 0.0)
        return close * (1 + half) if side == "buy" else close * (1 - half)

    def fee(self) -> float:
        return self.fee_eur if self.enabled else 0.0


def load_strategy(version: str):
    if version == "current":
        path = ROOT / "strategy" / "current.py"
    elif version.endswith(".py"):
        path = Path(version)
    else:
        matches = sorted((ROOT / "strategy" / "versions").glob(f"{version}_*.py"))
        if not matches:
            raise SystemExit(f"no frozen version matching {version}_*.py in strategy/versions/")
        path = matches[-1]
    spec = importlib.util.spec_from_file_location(f"strategy_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod, path


def metrics(nav: pd.Series, trades: int = 0, fees: float = 0.0, turnover_value: float = 0.0,
            days_invested: int | None = None) -> dict:
    nav = nav.dropna()
    if len(nav) < 2:
        return {}
    rets = nav.pct_change().dropna()
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / years) - 1 if years > 0 else float("nan")
    dd = nav / nav.cummax() - 1
    vol = rets.std() * math.sqrt(TRADING_DAYS)
    sharpe = (rets.mean() * TRADING_DAYS) / vol if vol > 0 else float("nan")
    out = {
        "start": nav.index[0].strftime("%Y-%m-%d"), "end": nav.index[-1].strftime("%Y-%m-%d"),
        "years": round(years, 2), "start_nav": round(float(nav.iloc[0]), 2), "end_nav": round(float(nav.iloc[-1]), 2),
        "total_return": round(float(nav.iloc[-1] / nav.iloc[0] - 1), 4), "cagr": round(float(cagr), 4),
        "max_drawdown": round(float(dd.min()), 4), "volatility": round(float(vol), 4),
        "sharpe": round(float(sharpe), 2), "calmar": round(float(cagr / abs(dd.min())), 2) if dd.min() < 0 else None,
        "worst_day": round(float(rets.min()), 4), "best_day": round(float(rets.max()), 4),
        "trades": trades, "fees_eur": round(fees, 2),
        "turnover_per_year": round(float(turnover_value / nav.mean() / years), 2) if years > 0 else None,
    }
    if days_invested is not None:
        out["time_invested_pct"] = round(days_invested / len(nav), 3)
    return out


def yearly(nav: pd.Series) -> dict[str, float]:
    y = nav.resample("YE").last()
    first = nav.iloc[0]
    out, prev = {}, first
    for ts, v in y.items():
        out[str(ts.year)] = round(float(v / prev - 1), 4)
        prev = v
    return out


def simulate(strategy, params: dict, closes: pd.DataFrame, universe: pd.DataFrame, *, start: pd.Timestamp,
             end: pd.Timestamp, initial: float, fr: Frictions, man: mandate_mod.Mandate) -> dict:
    types = dict(zip(universe["isin"], universe["type"]))
    names = dict(zip(universe["isin"], universe["name"]))
    days = closes.loc[start:end].index
    cash = initial
    qty: dict[str, float] = {}
    nav_hist, cash_hist, trade_log, rejected = [], [], [], []
    fees_paid = turnover = 0.0
    invested_days = 0
    lim = man.limits
    for t in days:
        row = closes.loc[t]
        # mark positions
        positions = []
        for isin, q in list(qty.items()):
            px = row.get(isin)
            if px is None or not np.isfinite(px):
                px = closes[isin].loc[:t].dropna().iloc[-1]
            positions.append(Position(isin=isin, name=names.get(isin, isin), quantity=q, price=float(px), value_eur=float(q * px), security_type=types.get(isin)))
        nav = cash + sum(p.value_eur for p in positions)
        state = PortfolioState(as_of=t.date(), nav=nav, cash=cash, buying_power=cash, positions=tuple(positions))
        market = MarketData(closes=closes, as_of=t.date(), universe=universe)
        orders: list[ProposedOrder] = strategy.generate(state, market, params)
        for o in orders[: lim.max_orders_per_day]:
            px_close = row.get(o.isin)
            if px_close is None or not np.isfinite(px_close):
                rejected.append({"date": str(t.date()), "isin": o.isin, "reason": "no close"})
                continue
            itype = types.get(o.isin, "stock")
            if o.side == "buy" and o.quantity is not None:
                # Whole-share buy (v002+): the order value is shares x price, the fee is on top.
                q = float(o.quantity)
                px = fr.exec_price(float(px_close), "buy", itype)
                fee = fr.fee()
                cost = q * px
                held_val = qty.get(o.isin, 0.0) * px_close
                if (q < 1 or not q.is_integer() or cost < lim.min_order_eur or cost > lim.max_order_pct_of_nav * nav + 1e-6
                        or cost + fee > cash - lim.cash_reserve_eur or held_val + cost > lim.max_position_pct_of_nav * nav + 1e-6):
                    rejected.append({"date": str(t.date()), "isin": o.isin, "reason": "mandate limit", "amount": cost})
                    continue
                qty[o.isin] = qty.get(o.isin, 0.0) + q
                cash -= cost + fee
                fees_paid += fee
                turnover += cost
                trade_log.append({"date": str(t.date()), "side": "buy", "isin": o.isin, "eur": round(cost, 2), "shares": q, "price": round(px, 4), "fee": fee})
            elif o.side == "buy":
                amount = float(o.eur_amount or 0.0)
                if amount < lim.min_order_eur or amount > lim.max_order_pct_of_nav * nav + 1e-6 or amount > cash - lim.cash_reserve_eur:
                    rejected.append({"date": str(t.date()), "isin": o.isin, "reason": "mandate limit", "amount": amount})
                    continue
                held_val = qty.get(o.isin, 0.0) * px_close
                if held_val + amount > lim.max_position_pct_of_nav * nav + 1e-6:
                    rejected.append({"date": str(t.date()), "isin": o.isin, "reason": "position limit", "amount": amount})
                    continue
                px = fr.exec_price(float(px_close), "buy", itype)
                fee = fr.fee()
                shares = (amount - fee) / px
                qty[o.isin] = qty.get(o.isin, 0.0) + shares
                cash -= amount
                fees_paid += fee
                turnover += amount
                trade_log.append({"date": str(t.date()), "side": "buy", "isin": o.isin, "eur": round(amount, 2), "price": round(px, 4), "fee": fee})
            else:
                q = float(o.quantity or 0.0)
                have = qty.get(o.isin, 0.0)
                if q <= 0 or q > have + 1e-9:
                    rejected.append({"date": str(t.date()), "isin": o.isin, "reason": "sell > held"})
                    continue
                px = fr.exec_price(float(px_close), "sell", itype)
                fee = fr.fee()
                proceeds = q * px - fee
                cash += proceeds
                fees_paid += fee
                turnover += q * px
                qty[o.isin] = have - q
                if qty[o.isin] <= 1e-9:
                    del qty[o.isin]
                trade_log.append({"date": str(t.date()), "side": "sell", "isin": o.isin, "eur": round(q * px, 2), "price": round(px, 4), "fee": fee})
        nav_hist.append(cash + sum(qty.get(i, 0) * (row.get(i) if np.isfinite(row.get(i, np.nan)) else closes[i].loc[:t].dropna().iloc[-1]) for i in qty))
        cash_hist.append(cash)
        if qty:
            invested_days += 1
    nav_s = pd.Series(nav_hist, index=days, name="nav")
    return {"nav": nav_s, "cash": pd.Series(cash_hist, index=days), "trades": trade_log, "rejected": rejected,
            "fees": fees_paid, "turnover": turnover, "invested_days": invested_days,
            "final_positions": {i: round(q, 6) for i, q in qty.items()}}


def benchmark_series(closes: pd.DataFrame, isin: str, itype: str, days: pd.DatetimeIndex, initial: float, fr: Frictions) -> pd.Series:
    s = closes[isin].reindex(days).ffill()
    px = fr.exec_price(float(s.iloc[0]), "buy", itype)
    units = (initial - fr.fee()) / px
    return pd.Series(units * s.to_numpy(), index=days, name="benchmark")


def make_chart(nav: pd.Series, bench: pd.Series, out: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(nav.index, nav.values, label="strategy", color="#2563eb", lw=1.4)
    ax1.plot(bench.index, bench.values, label="benchmark (MSCI World)", color="#9ca3af", lw=1.2)
    ax1.set_yscale("log")
    ax1.set_ylabel("NAV (EUR, log)")
    ax1.set_title(title)
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)
    for s, c in ((nav, "#2563eb"), (bench, "#9ca3af")):
        dd = s / s.cummax() - 1
        ax2.fill_between(dd.index, dd.values, 0, color=c, alpha=0.35)
    ax2.set_ylabel("drawdown")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default="current")
    ap.add_argument("--params", default=None, help="params.toml to use (default: strategy/params.toml)")
    ap.add_argument("--start", default=None, help="first decision day (default: when 260 days of history exist)")
    ap.add_argument("--end", default=None)
    ap.add_argument("--initial", type=float, default=1000.0)
    ap.add_argument("--no-costs", action="store_true", help="ignore fees and spreads (for comparison only)")
    ap.add_argument("--out", default=None, help="output JSON path (default research/backtests/<version>.json)")
    ap.add_argument("--no-chart", action="store_true")
    ap.add_argument("--label", default=None)
    args = ap.parse_args(argv)

    t0 = time.time()
    strategy, spath = load_strategy(args.version)
    params = strategy.load_params(Path(args.params)) if args.params else strategy.load_params()
    label = args.label or params.get("version", spath.stem)
    man = mandate_mod.load()
    universe = data_mod.load_universe()
    closes = data_mod.closes_by_isin()
    if closes.empty:
        raise SystemExit("empty price cache; run strategy/data.py --full")
    closes = closes.sort_index()
    fr = Frictions(fee_eur=man.order_fee_eur, crypto_surcharge=man.crypto_etp_spread_surcharge, enabled=not args.no_costs)

    bench_isin = man.benchmark_isin
    warmup = int(params.get("momentum", {}).get("min_history_days", 260)) + 5
    first_possible = closes.index[min(warmup, len(closes) - 1)]
    start = pd.Timestamp(args.start) if args.start else first_possible
    start = max(start, first_possible)
    end = pd.Timestamp(args.end) if args.end else closes.index.max()

    sim = simulate(strategy, params, closes, universe, start=start, end=end, initial=args.initial, fr=fr, man=man)
    nav = sim["nav"]
    bench = benchmark_series(closes, bench_isin, "etf", nav.index, args.initial, fr)

    cut = int(len(nav) * 0.7)
    result = {
        "version": label, "strategy_file": str(spath.relative_to(ROOT)) if spath.is_relative_to(ROOT) else str(spath),
        "params": params, "generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frictions": {"enabled": fr.enabled, "fee_eur": fr.fee_eur, "spread": SPREAD, "crypto_surcharge": fr.crypto_surcharge,
                      "execution": "same-day close +/- half spread"},
        "data": {"source": "yfinance daily closes (EUR listings)", "instruments": int(closes.shape[1]),
                 "first_close": closes.index.min().strftime("%Y-%m-%d"), "last_close": closes.index.max().strftime("%Y-%m-%d")},
        "period": {"start": nav.index[0].strftime("%Y-%m-%d"), "end": nav.index[-1].strftime("%Y-%m-%d"), "days": int(len(nav))},
        "strategy": metrics(nav, len(sim["trades"]), sim["fees"], sim["turnover"], sim["invested_days"]),
        "benchmark": metrics(bench, 1, fr.fee()),
        "in_sample": {"strategy": metrics(nav.iloc[:cut]), "benchmark": metrics(bench.iloc[:cut])},
        "out_of_sample": {"strategy": metrics(nav.iloc[cut:]), "benchmark": metrics(bench.iloc[cut:])},
        "yearly": {"strategy": yearly(nav), "benchmark": yearly(bench)},
        "rejected_orders": len(sim["rejected"]), "rejected_sample": sim["rejected"][:20],
        "final_positions": sim["final_positions"],
        "trades_sample": sim["trades"][-20:],
        "equity_curve": [{"date": d.strftime("%Y-%m-%d"), "nav": round(float(v), 2), "benchmark": round(float(b), 2)}
                         for d, v, b in zip(nav.index, nav.values, bench.values)][:: max(1, len(nav) // 400)],
        "runtime_seconds": None,
    }
    out = Path(args.out) if args.out else ROOT / "research" / "backtests" / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not args.no_chart:
        make_chart(nav, bench, out.with_suffix(".png"), f"{label}: strategy vs MSCI World buy-and-hold ({result['period']['start']} to {result['period']['end']})")
        result["chart"] = str(out.with_suffix(".png").relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out.with_suffix(".png"))
    result["runtime_seconds"] = round(time.time() - t0, 1)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")

    s, b = result["strategy"], result["benchmark"]
    print(f"{label}  {result['period']['start']} -> {result['period']['end']}  ({result['runtime_seconds']}s)")
    print(f"{'':12s}{'strategy':>12s}{'benchmark':>12s}")
    for k in ("cagr", "total_return", "max_drawdown", "sharpe", "volatility", "trades", "fees_eur", "turnover_per_year", "end_nav"):
        print(f"{k:12s}{str(s.get(k)):>12s}{str(b.get(k)):>12s}")
    print(f"in-sample CAGR  {result['in_sample']['strategy'].get('cagr')} vs {result['in_sample']['benchmark'].get('cagr')}")
    print(f"out-of-sample   {result['out_of_sample']['strategy'].get('cagr')} vs {result['out_of_sample']['benchmark'].get('cagr')}")
    print(f"rejected by mandate limits: {result['rejected_orders']}   written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
