"""Research 2026-11-07: read-only measurements, no strategy change.

Answers the inbox questions of 2026-11-04 and 2026-11-05 on the v002 backtest, plus one
calibration of the live week. Thresholds fixed before the run (taken from the inbox
items, not tuned):

A. Weekly (Friday to Friday) NAV returns of v002: where does a -7.5% week sit?
B. Inbox 2026-11-04: holdings that fell more than 8% over the 10 trading days before
   an exit window and were nevertheless kept through it. What did they do over the
   next 21 trading days, absolute and against MSCI World, compared with all kept
   holdings?
C. Inbox 2026-11-05: months in which the book lost more than 10% (peak to trough)
   between the end of one exit window and the start of the next, with no sale in
   between. How often, and what came next?

    uv run python research/candidates/2026-11-07_study.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from finance import mandate as mandate_mod  # noqa: E402
from strategy import backtest as bt  # noqa: E402
from strategy import data as data_mod  # noqa: E402

PRE_DAYS, PRE_DROP = 10, -0.08     # inbox 2026-11-04: "more than ~8% in the two weeks before"
BOOK_DD = -0.10                     # inbox 2026-11-05: "more than ~10% between two exit windows"
FWD = 21
WINDOW = 3


def main() -> int:
    man = mandate_mod.load()
    universe = data_mod.load_universe()
    names = dict(zip(universe["isin"], universe["name"]))
    closes = data_mod.closes_by_isin().sort_index()
    fr = bt.Frictions(fee_eur=man.order_fee_eur, crypto_surcharge=man.crypto_etp_spread_surcharge)
    strategy, _ = bt.load_strategy("current")
    params = strategy.load_params()
    warm = int(params["momentum"]["min_history_days"]) + 5
    start, end = closes.index[warm], closes.index.max()
    sim = bt.simulate(strategy, params, closes, universe, start=start, end=end, initial=1000.0, fr=fr, man=man)
    nav = sim["nav"]
    days = nav.index
    bench = closes[man.benchmark_isin].ffill()
    print(f"v002 simulation {days[0].date()} -> {days[-1].date()}, {len(sim['trades'])} trades")

    # A. weekly returns
    wk = nav.resample("W-FRI").last().pct_change().dropna()
    print(f"\n## A. weekly returns: n={len(wk)}, mean {wk.mean():+.2%}, sd {wk.std():.2%}")
    for th in (-0.05, -0.075, -0.10):
        print(f"  weeks <= {th:+.1%}: {(wk <= th).sum()} ({(wk <= th).mean():.1%})")
    print("  worst 8 weeks:", ", ".join(f"{d.date()} {v:+.1%}" for d, v in wk.nsmallest(8).items()))

    # holdings at the start of each day (before that day's orders)
    by_day: dict = {}
    for t in sim["trades"]:
        by_day.setdefault(t["date"], []).append(t)
    held_at: dict = {}
    held: set = set()
    for d in days:
        held_at[d] = set(held)
        for t in by_day.get(str(d.date()), []):
            (held.add if t["side"] == "buy" else held.discard)(t["isin"])
    sells = {(t["date"], t["isin"]) for t in sim["trades"] if t["side"] == "sell"}
    sell_dates = sorted({pd.Timestamp(t["date"]) for t in sim["trades"] if t["side"] == "sell"})

    month_first = [i for i in range(1, len(days)) if days[i].month != days[i - 1].month]

    # B. pre-window drop, kept through the window
    rows = []
    for i in month_first:
        if i + WINDOW + FWD >= len(days) or i - PRE_DAYS - 1 < 0:
            continue
        d0, dprev, dend = days[i], days[i - 1], days[i + WINDOW - 1]
        win = {str(days[j].date()) for j in range(i, i + WINDOW)}
        dfwd = days[i + WINDOW - 1 + FWD]
        for isin in held_at[d0]:
            if any((w, isin) in sells for w in win):
                continue                                   # sold in the window
            s = closes[isin].ffill()
            pre = s[dprev] / s[days[i - 1 - PRE_DAYS]] - 1
            fwd = s[dfwd] / s[dend] - 1
            bfwd = bench[dfwd] / bench[dend] - 1
            rows.append({"window": str(d0.date()), "isin": isin, "name": names.get(isin, isin)[:30],
                         "pre10": pre, "fwd21": fwd, "excess": fwd - bfwd})
    df = pd.DataFrame(rows)
    print(f"\n## B. kept holdings after {len(month_first)} exit windows: {len(df)} position-windows "
          f"(forward = {FWD} trading days after the window's last day)")
    for lab, g in [(f"fell > {-PRE_DROP:.0%} in prior {PRE_DAYS}d", df[df.pre10 < PRE_DROP]),
                   ("all other kept", df[df.pre10 >= PRE_DROP]), ("all kept", df)]:
        if g.empty:
            print(f"  {lab:28s} n=0")
            continue
        se = g.excess.std() / np.sqrt(len(g)) if len(g) > 1 else float("nan")
        print(f"  {lab:28s} n={len(g):3d}  fwd mean {g.fwd21.mean():+.2%} median {g.fwd21.median():+.2%}  "
              f"excess mean {g.excess.mean():+.2%} (se {se:.2%}) median {g.excess.median():+.2%}  "
              f"hit {(g.excess > 0).mean():.0%}  fwd<-10% {(g.fwd21 < -0.10).mean():.0%}")
    big = df[df.pre10 < PRE_DROP]
    if not big.empty:
        print(big.round(3).to_string(index=False))

    # C. book drawdown between windows, no sale
    print(f"\n## C. spans between exit windows (window day {WINDOW + 1} to the day before the next window)")
    spans = []
    for a, b in zip(month_first[:-1], month_first[1:]):
        lo, hi = a + WINDOW, b - 1
        if lo > hi:
            continue
        seg = nav.iloc[lo - 1:hi + 1]                     # include the window's last close as the starting peak
        no_sale = not any(days[lo] <= sd <= days[hi] for sd in sell_dates)
        dd = (seg / seg.cummax() - 1).min()
        nxt_end = min(b + WINDOW - 1 + FWD, len(days) - 1)
        after = nav.iloc[nxt_end] / nav.iloc[hi] - 1
        spans.append({"month": days[lo].strftime("%Y-%m"), "span_ret": seg.iloc[-1] / seg.iloc[0] - 1,
                      "max_dd": dd, "no_sale": no_sale, "next_month_ret": after,
                      "invested": bool(held_at[days[lo]])})
    sp = pd.DataFrame(spans)
    inv = sp[sp.invested]
    hit = inv[(inv.max_dd < BOOK_DD) & inv.no_sale]
    print(f"  spans: {len(sp)}, invested at start: {len(inv)}; with max DD < {BOOK_DD:.0%} and no sale: {len(hit)} "
          f"({len(hit) / max(len(inv), 1):.1%}); with max DD < {BOOK_DD:.0%} incl. a trend sale: "
          f"{int(((inv.max_dd < BOOK_DD) & ~inv.no_sale).sum())}")
    if not hit.empty:
        print(hit.round(3).to_string(index=False))
        print(f"  after those spans, next month (to {FWD}d after the next window): mean {hit.next_month_ret.mean():+.2%}, "
              f"median {hit.next_month_ret.median():+.2%}; all invested spans: mean {inv.next_month_ret.mean():+.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
