"""Candidate 2026-10-24 one_per_group: v002 plus a one-per-group entry rule.

    generate(state, market, params) -> list[ProposedOrder]

Identical to strategy v002 (strategy/current.py at 2026-10-24) except for one rule:

7. Groups (new): `[groups]` in the params file maps ISINs to a group name for
   instruments that are near-duplicates (two energy-sector funds, the tech/semiconductor
   cluster, two financials funds, ...). An entry candidate is skipped while another
   instrument of its group is held or is being bought the same day; the next
   best-ranked instrument of a different group takes the slot. Instruments not listed
   are their own group. Exits are unchanged: a duplicate already held is not sold
   because of this rule.
"""
from __future__ import annotations

import math
import sys
import tomllib
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from finance.models import MarketData, PortfolioState, ProposedOrder  # noqa: E402

VERSION = "candidate_one_per_group"
PARAMS_PATH = Path(__file__).with_suffix(".toml")


def load_params(path: Path | None = None) -> dict:
    with (path or PARAMS_PATH).open("rb") as fh:
        return tomllib.load(fh)


def _trading_days_this_month(index: pd.DatetimeIndex, as_of: pd.Timestamp) -> int:
    month = index[(index.year == as_of.year) & (index.month == as_of.month) & (index <= as_of)]
    return len(month)


def _group_of(params: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for group, isins in params.get("groups", {}).items():
        for isin in isins:
            out[isin] = group
    return out


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
    group_of = _group_of(params)

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
    # Groups already occupied by a kept position (candidate rule 7).
    taken_groups = {group_of.get(p.isin, p.isin) for p in keep}
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
        group = group_of.get(r["isin"], r["isin"])
        if group in taken_groups:
            continue
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
        taken_groups.add(group)
        spendable -= est * buffer

    # Top-ups for kept positions that drifted well below target are deliberately not
    # done: they add fees without changing the signal.
    sells.sort(key=lambda o: rank.get(o.isin, {}).get("rank", 10_000), reverse=True)
    orders = sells + buys
    return orders[: int(p_sz["max_orders_per_day"])]
