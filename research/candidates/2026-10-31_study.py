"""Research 2026-10-31: read-only study, no strategy change.

1. Scan the price cache for one-day spike-and-revert rows.
2. Re-run the v002 backtest with those cells blanked, to measure their effect.
3. Check the momentum endpoints (t-21, t-252) of the 2-4 Nov 2026 exit window.
4. Skip-month question (inbox 2026-10-30): held positions that fell more than 10% in
   the 21 days before the first day of an exit window, and what they did next.

    uv run python research/candidates/2026-10-31_study.py
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

JUMP, REVERT = 0.08, 0.03   # fixed before the run: >8% one-day move, next day back within 3% of the day before


def spikes(closes: pd.DataFrame, names: dict) -> pd.DataFrame:
    rows = []
    for isin in closes.columns:
        s = closes[isin].dropna()
        if len(s) < 3:
            continue
        prev, cur, nxt = s.shift(1), s, s.shift(-1)
        jump = cur / prev - 1
        back = nxt / prev - 1
        flag = (jump.abs() > JUMP) & (back.abs() < REVERT) & (np.sign(jump) != np.sign(nxt / cur - 1))
        for d in s.index[flag.fillna(False).to_numpy()]:
            rows.append({"date": d.strftime("%Y-%m-%d"), "isin": isin, "name": names.get(isin, isin)[:32],
                         "prev": round(float(prev[d]), 3), "close": round(float(cur[d]), 3),
                         "next": round(float(nxt[d]), 3), "jump": round(float(jump[d]), 3)})
    return pd.DataFrame(rows).sort_values(["date", "isin"]) if rows else pd.DataFrame()


def run(strategy, params, closes, universe, man, fr):
    warm = int(params["momentum"]["min_history_days"]) + 5
    start, end = closes.index[warm], closes.index.max()
    sim = bt.simulate(strategy, params, closes, universe, start=start, end=end, initial=1000.0, fr=fr, man=man)
    nav = sim["nav"]
    cut = int(len(nav) * 0.7)
    m = bt.metrics(nav, len(sim["trades"]), sim["fees"], sim["turnover"], sim["invested_days"])
    return sim, m, bt.metrics(nav.iloc[:cut]), bt.metrics(nav.iloc[cut:])


def holdings_by_day(trades: list[dict], days: pd.DatetimeIndex) -> dict:
    """Positions held at the start of each day (before that day's orders)."""
    by_day: dict = {}
    for t in trades:
        by_day.setdefault(t["date"], []).append(t)
    held: set = set()
    out = {}
    for d in days:
        out[d] = set(held)
        for t in by_day.get(str(d.date()), []):
            if t["side"] == "buy":
                held.add(t["isin"])
            else:
                held.discard(t["isin"])
    return out


def main() -> int:
    man = mandate_mod.load()
    universe = data_mod.load_universe()
    names = dict(zip(universe["isin"], universe["name"]))
    closes = data_mod.closes_by_isin().sort_index()
    fr = bt.Frictions(fee_eur=man.order_fee_eur, crypto_surcharge=man.crypto_etp_spread_surcharge)
    strategy, _ = bt.load_strategy("current")
    params = strategy.load_params()

    # 1. Spike scan
    sp = spikes(closes, names)
    print(f"## 1. spike-and-revert cells (|jump| > {JUMP:.0%}, next close within {REVERT:.0%} of the day before): {len(sp)}")
    if not sp.empty:
        print(sp.to_string(index=False))
        print("\nby date:", sp.groupby("date").size().to_dict())

    # 2. Backtest with the flagged cells blanked
    clean = closes.copy()
    for r in sp.itertuples():
        clean.loc[pd.Timestamp(r.date), r.isin] = np.nan
    sim0, m0, is0, oos0 = run(strategy, params, closes, universe, man, fr)
    sim1, m1, is1, oos1 = run(strategy, params, clean, universe, man, fr)
    print("\n## 2. v002 with and without the flagged cells")
    keys = ["cagr", "max_drawdown", "sharpe", "trades", "fees_eur", "turnover_per_year", "end_nav"]
    print(f"{'':20s}{'as cached':>12s}{'spikes blanked':>16s}")
    for k in keys:
        print(f"{k:20s}{str(m0.get(k)):>12s}{str(m1.get(k)):>16s}")
    print(f"{'IS cagr':20s}{str(is0.get('cagr')):>12s}{str(is1.get('cagr')):>16s}")
    print(f"{'OOS cagr':20s}{str(oos0.get('cagr')):>12s}{str(oos1.get('cagr')):>16s}")
    print(f"{'OOS max_drawdown':20s}{str(oos0.get('max_drawdown')):>12s}{str(oos1.get('max_drawdown')):>16s}")
    t0 = {(t["date"], t["side"], t["isin"]) for t in sim0["trades"]}
    t1 = {(t["date"], t["side"], t["isin"]) for t in sim1["trades"]}
    diff = sorted(t0 ^ t1)
    print(f"trades differing: {len(diff)}; first divergence: {diff[0] if diff else None}")

    # 3. Endpoints for the 2-4 Nov 2026 window (next three trading days after the cache end)
    idx = closes.index
    n = len(idx)
    flagged = set(sp["date"]) if not sp.empty else set()
    print(f"\n## 3. exit-window endpoints (cache ends {idx[-1].date()})")
    for k, day in enumerate(["2026-11-02", "2026-11-03", "2026-11-04"]):
        pos = n + k   # position the new day will take
        t21, t252 = idx[pos - 21], idx[pos - 252]   # s.iloc[-1 - 21], s.iloc[-1 - 252] once the new day is the last row
        print(f"{day}: t-21 = {t21.date()} {'SPIKE' if str(t21.date()) in flagged else 'clean'}, "
              f"t-252 = {t252.date()} {'SPIKE' if str(t252.date()) in flagged else 'clean'}")

    # 4. Skip-month study on the as-cached run
    days = sim0["nav"].index
    held = holdings_by_day(sim0["trades"], days)
    month_first = [d for i, d in enumerate(days) if i > 0 and d.month != days[i - 1].month]
    bench = man.benchmark_isin
    sold_in_window = {}
    for t in sim0["trades"]:
        if t["side"] == "sell":
            sold_in_window.setdefault(t["isin"], set()).add(t["date"])
    rows = []
    for d in month_first:
        pos = closes.index.get_loc(d)
        if pos + 21 >= len(closes.index):
            continue
        d_back, d_fwd = closes.index[pos - 21], closes.index[pos + 21]
        win = [str(x.date()) for x in closes.index[pos:pos + 3]]
        for isin in held[d]:
            s = closes[isin].ffill()
            prior = s[closes.index[pos - 1]] / s[d_back] - 1   # the 21 days ending the day before the window
            fwd = s[d_fwd] / s[closes.index[pos - 1]] - 1
            b = closes[bench].ffill()
            bfwd = b[d_fwd] / b[closes.index[pos - 1]] - 1
            sold = any(w in sold_in_window.get(isin, set()) for w in win)
            rows.append({"date": str(d.date()), "isin": isin, "prior21": prior, "fwd21": fwd, "excess": fwd - bfwd, "sold": sold})
    df = pd.DataFrame(rows)
    print(f"\n## 4. held positions at the start of {len(month_first)} exit windows: {len(df)} position-windows")
    for lab, g in [("fell >10% in prior 21d", df[df.prior21 < -0.10]),
                   ("fell 5-10%", df[(df.prior21 >= -0.10) & (df.prior21 < -0.05)]),
                   ("other", df[df.prior21 >= -0.05]),
                   ("all", df)]:
        if g.empty:
            print(f"{lab:24s} n=0")
            continue
        print(f"{lab:24s} n={len(g):3d}  sold in window {int(g.sold.sum()):3d}  "
              f"next-21d mean {g.fwd21.mean():+.2%} median {g.fwd21.median():+.2%}  "
              f"excess vs MSCI World mean {g.excess.mean():+.2%} median {g.excess.median():+.2%}  "
              f"hit rate (excess>0) {(g.excess > 0).mean():.0%}")
    big = df[df.prior21 < -0.10]
    if not big.empty:
        kept = big[~big.sold]
        print(f"\nfell >10% and kept through the window: n={len(kept)}, next-21d excess mean {kept.excess.mean():+.2%}, "
              f"median {kept.excess.median():+.2%}, std {kept.excess.std():.2%}, "
              f"t-stat {kept.excess.mean() / (kept.excess.std() / np.sqrt(len(kept))) if len(kept) > 1 else float('nan'):.2f}")
        out = big.assign(name=big.isin.map(lambda i: names.get(i, i)[:28]))
        print(out[["date", "name", "prior21", "fwd21", "excess", "sold"]].round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
