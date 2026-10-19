"""Strategy v002: trend-filtered 12-1 momentum rotation with hysteresis.

    generate(state, market, params) -> list[ProposedOrder]

Pure and deterministic: it reads only its arguments. No network, no clock, no files.
The daily session runs it, pastes the output verbatim into the journal, and may only
refuse to trade. See STRATEGY.md for the reasoning and the changelog.

Rules (all parameters in strategy/params.toml):
1. Trend filter with a band: new positions are only opened while the MSCI World ETF
   closes above its 200-day SMA; everything is sold once it closes more than
   `exit_band` below the SMA. In between, existing positions are held (no churn
   from the index hovering around its average).
2. Ranking: 12-1 month momentum = close[t-21] / close[t-252] - 1 over the risk
   sleeve (ETFs, stocks, ETCs, crypto ETP; cash proxies excluded).
3. Exits, in the first `rebalance_window_days` trading days of each month only:
   momentum below zero (absolute momentum) or rank worse than `hold_rank`.
   Outside the window a position is only sold by the trend filter.
4. Entries: whenever fewer than `top_n` sleeve positions are held, buy the best-ranked
   instruments not held, one slot each, in rank order, skipping any whose single
   share costs more than the slot.
5. Sizing (v002): whole shares, floor(budget / (close * (1 + price_buffer))), where
   budget = min(target 1/top_n of NAV, `order_cap_pct_of_nav` of NAV, spendable cash).
   Buys worth less than `min_order_eur` are skipped. Sells are whole positions.
6. At most `max_orders_per_day` orders, sells first. The rest wait for tomorrow.
"""
from __future__ import annotations

import math
import sys
import tomllib
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance.models import MarketData, PortfolioState, ProposedOrder  # noqa: E402

VERSION = "v002"
PARAMS_PATH = Path(__file__).resolve().parent / "params.toml"


def load_params(path: Path | None = None) -> dict:
    with (path or PARAMS_PATH).open("rb") as fh:
        return tomllib.load(fh)


def _trading_days_this_month(index: pd.DatetimeIndex, as_of: pd.Timestamp) -> int:
    month = index[(index.year == as_of.year) & (index.month == as_of.month) & (index <= as_of)]
    return len(month)


def signals(market: MarketData, params: dict) -> dict:
    """Everything the decision needs, as plain numbers, so the journal can show them."""
    hist = market.history()
    p_tr, p_mo, p_sel = params["trend"], params["momentum"], params["selection"]
    as_of = pd.Timestamp(market.as_of)
    out: dict = {"as_of": market.as_of.isoformat(), "version": params.get("version", VERSION)}

    bench = p_tr["isin"]
    if bench not in hist.columns or hist[bench].dropna().shape[0] < p_tr["sma_days"]:
        out["trend_on"] = False
        out["trend_exit"] = True
        out["trend_note"] = f"trend series {bench} missing or shorter than {p_tr['sma_days']} days: treated as trend OFF"
        out["ranking"] = []
        return out
    b = hist[bench].dropna()
    sma = b.rolling(p_tr["sma_days"]).mean().iloc[-1]
    last = b.iloc[-1]
    band = float(p_tr.get("exit_band", 0.0))
    out["trend_on"] = bool(last > sma)                      # entries allowed
    out["trend_exit"] = bool(last < sma * (1.0 - band))      # everything is sold
    out["trend_close"] = round(float(last), 4)
    out["trend_sma"] = round(float(sma), 4)
    out["trend_last_date"] = b.index[-1].strftime("%Y-%m-%d")

    sleeve = market.universe[market.universe["type"].isin(p_sel["sleeve_types"])]
    look, skip, min_hist = p_mo["lookback_days"], p_mo["skip_days"], p_mo["min_history_days"]
    rows = []
    for row in sleeve.itertuples():
        if row.isin not in hist.columns:
            continue
        s = hist[row.isin].dropna()
        if len(s) < max(min_hist, look + 1):
            continue
        # The strategy runs after the close, so the last row is "today".
        mom = float(s.iloc[-1 - skip] / s.iloc[-1 - look] - 1.0)
        if not math.isfinite(mom):
            continue
        rows.append({"isin": row.isin, "name": row.name, "type": row.type, "momentum": mom,
                     "last_close": float(s.iloc[-1]), "last_date": s.index[-1].strftime("%Y-%m-%d")})
    rows.sort(key=lambda r: (-r["momentum"], r["isin"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["momentum"] = round(r["momentum"], 4)
    out["ranking"] = rows
    out["rebalance_window"] = _trading_days_this_month(hist.index, as_of) <= p_sel["rebalance_window_days"]
    out["trading_day_of_month"] = _trading_days_this_month(hist.index, as_of)
    return out


def generate(state: PortfolioState, market: MarketData, params: dict) -> list[ProposedOrder]:
    sig = signals(market, params)
    p_sel, p_sz = params["selection"], params["sizing"]
    top_n, hold_rank = int(p_sel["top_n"]), int(p_sel["hold_rank"])
    rank = {r["isin"]: r for r in sig["ranking"]}
    sleeve_isins = set(market.universe.loc[market.universe["type"].isin(p_sel["sleeve_types"]), "isin"])
    names = dict(zip(market.universe["isin"], market.universe["name"]))

    held = [p for p in state.positions if p.isin in sleeve_isins and p.quantity > 0]
    sells: list[ProposedOrder] = []
    buys: list[ProposedOrder] = []

    if sig.get("trend_exit"):
        note = sig.get("trend_note") or (
            f"trend filter OFF: {params['trend']['isin']} close {sig['trend_close']} is more than "
            f"{float(params['trend'].get('exit_band', 0.0)):.0%} below SMA{params['trend']['sma_days']} {sig['trend_sma']}")
        for p in held:
            sells.append(ProposedOrder(isin=p.isin, side="sell", quantity=p.quantity, name=p.name,
                                       rationale=f"Exit whole position: {note}."))
        sells.sort(key=lambda o: o.isin)
        return sells[: int(p_sz["max_orders_per_day"])]

    window_only = bool(p_sel.get("exits_only_in_rebalance_window", True))
    in_window = sig["rebalance_window"] or not window_only
    keep: list = []
    for p in held:
        r = rank.get(p.isin)
        if r is None:
            sells.append(ProposedOrder(isin=p.isin, side="sell", quantity=p.quantity, name=p.name,
                                       rationale="Exit whole position: instrument no longer rankable (missing data or dropped from universe)."))
            continue
        if in_window and p_sel.get("exit_on_negative_momentum", True) and r["momentum"] < 0:
            sells.append(ProposedOrder(isin=p.isin, side="sell", quantity=p.quantity, name=p.name,
                                       rationale=f"Exit whole position at monthly rebalance: 12-1 momentum {r['momentum']:+.1%} is negative (rank {r['rank']})."))
            continue
        if in_window and r["rank"] > hold_rank:
            sells.append(ProposedOrder(isin=p.isin, side="sell", quantity=p.quantity, name=p.name,
                                       rationale=f"Exit whole position at monthly rebalance: rank {r['rank']} is worse than hold rank {hold_rank} (momentum {r['momentum']:+.1%})."))
            continue
        keep.append(p)

    # Entries: fill free slots with the best-ranked instruments we do not hold.
    keep_isins = {p.isin for p in keep}
    slots = top_n - len(keep)
    nav = state.nav
    spendable = state.cash - float(p_sz["cash_reserve_eur"]) - state.pending_buy_orders_eur
    # Cash freed by today's sells is not available until they fill; do not pre-spend it.
    target_value = nav * float(p_sz["target_weight"])
    order_cap = nav * float(p_sz["order_cap_pct_of_nav"])
    min_order = float(p_sz["min_order_eur"])

    # Whole shares only: Scalable fills one-off orders in whole shares (verified
    # 2026-10-19), so each buy is a share count sized at the last close plus a buffer
    # for the ask and the move to 18:15. Candidates whose single share does not fit
    # the slot are passed over for the next affordable one.
    buffer = 1.0 + float(p_sz["price_buffer"])
    candidates = [] if not sig["trend_on"] else \
        [r for r in sig["ranking"] if r["isin"] not in keep_isins and r["momentum"] > 0]
    for r in candidates:
        if len(buys) >= slots:
            break
        current = state.weight(r["isin"]) * nav
        budget = min(target_value - current, order_cap, spendable)
        price = float(r["last_close"])
        shares = math.floor(budget / (price * buffer)) if price > 0 else 0
        est = shares * price
        if shares < 1 or est < min_order:
            continue
        buys.append(ProposedOrder(
            isin=r["isin"], side="buy", quantity=float(shares), name=names.get(r["isin"], r["name"]),
            rationale=(f"Enter: rank {r['rank']} of {len(sig['ranking'])} by 12-1 momentum ({r['momentum']:+.1%}); "
                       f"trend ON ({params['trend']['isin']} {sig['trend_close']} > SMA{params['trend']['sma_days']} {sig['trend_sma']}); "
                       f"{shares} shares at about {price:.2f} EUR = {est:.2f} EUR, target weight {p_sz['target_weight']:.0%} of NAV {nav:.2f} EUR."),
        ))
        spendable -= est * buffer

    # Top-ups for kept positions that drifted well below target are deliberately not
    # done: they add fees without changing the signal.
    sells.sort(key=lambda o: rank.get(o.isin, {}).get("rank", 10_000), reverse=True)
    orders = sells + buys
    return orders[: int(p_sz["max_orders_per_day"])]


def main() -> int:
    """`uv run python strategy/current.py` prints signals and proposals for the
    latest snapshot. Read-only; it never touches trade files."""
    import json
    import os
    from finance import clock, portfolio
    from strategy import data as data_mod

    params = load_params()
    dry_run = os.environ.get("FINANCE_DRY_RUN") == "1"
    today = clock.today()
    md = data_mod.market_data(as_of=today)   # closes after the session date are never visible (replays)
    state = portfolio.latest_state(today, dry_run=dry_run)
    if state is None:
        print(f"no portfolio snapshot for {today}{' (dry run)' if dry_run else ''}; run bin/snapshot.py first", file=sys.stderr)
        return 2
    if state.as_of != today:
        print(f"warning: latest snapshot is from {state.as_of}, not {today}", file=sys.stderr)
    sig = signals(md, params)
    orders = generate(state, md, params)
    print(json.dumps({"version": params.get("version", VERSION), "signals": sig,
                      "state": {"as_of": state.as_of.isoformat(), "dry_run": state.dry_run, "nav": state.nav, "cash": state.cash,
                                "positions": [p.isin for p in state.positions]},
                      "proposed_orders": [o.to_dict() for o in orders]}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
