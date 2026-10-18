from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from finance.models import MarketData, PortfolioState, Position
from strategy import current, data as data_mod

PARAMS = current.load_params()
BENCH = PARAMS["trend"]["isin"]


def synthetic_market(as_of: date, trend_up: bool = True, n: int = 400) -> MarketData:
    """Deterministic closes for the whole universe. Instrument i grows at a rate that
    makes the ranking unambiguous: rank 1 is the strongest grower."""
    u = data_mod.load_universe()
    idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=n)
    cols = {}
    sleeve = u[u["type"].isin(PARAMS["selection"]["sleeve_types"])]
    for i, row in enumerate(sleeve.itertuples()):
        rate = 0.0025 - i * 0.0001          # first rows strongest; later ones negative momentum
        cols[row.isin] = 100.0 * np.cumprod(1 + np.full(n, rate))
    for row in u[u["type"] == "cash"].itertuples():
        cols[row.isin] = 100.0 * np.cumprod(1 + np.full(n, 0.00005))
    df = pd.DataFrame(cols, index=idx)
    if not trend_up:
        # Put the benchmark under its SMA200 by crashing the last 60 days.
        b = df[BENCH].to_numpy().copy()
        b[-60:] = b[-60:] * np.linspace(1.0, 0.6, 60)
        df[BENCH] = b
    return MarketData(closes=df, as_of=as_of, universe=u)


def state(nav=1000.0, cash=1000.0, positions=()):
    return PortfolioState(as_of=date(2026, 10, 20), nav=nav, cash=cash, buying_power=cash, positions=tuple(positions))


def test_generate_is_pure_and_deterministic():
    md = synthetic_market(date(2026, 10, 20))
    s = state()
    a = current.generate(s, md, PARAMS)
    b = current.generate(s, md, PARAMS)
    assert a == b


def test_trend_on_buys_top_ranked_within_daily_limit_and_caps():
    md = synthetic_market(date(2026, 10, 20))
    orders = current.generate(state(), md, PARAMS)
    assert len(orders) == PARAMS["sizing"]["max_orders_per_day"]
    assert all(o.side == "buy" for o in orders)
    sig = current.signals(md, PARAMS)
    top = [r["isin"] for r in sig["ranking"][:2]]
    assert [o.isin for o in orders] == top
    cap = 1000.0 * PARAMS["sizing"]["order_cap_pct_of_nav"]
    assert all(o.eur_amount <= cap for o in orders)
    assert all(o.eur_amount >= PARAMS["sizing"]["min_order_eur"] for o in orders)
    assert all("rank" in o.rationale for o in orders)


def test_trend_off_sells_everything_and_buys_nothing():
    md = synthetic_market(date(2026, 10, 20), trend_up=False)
    sig = current.signals(md, PARAMS)
    assert sig["trend_on"] is False
    held = [Position(isin="IE00B5BMR087", name="x", quantity=1.5, price=100, value_eur=150),
            Position(isin="DE0007164600", name="y", quantity=2, price=100, value_eur=200)]
    orders = current.generate(state(cash=650, positions=held), md, PARAMS)
    assert {o.side for o in orders} == {"sell"}
    assert {o.isin for o in orders} == {"IE00B5BMR087", "DE0007164600"}
    assert all(o.quantity in (1.5, 2) for o in orders)


def test_held_negative_momentum_is_sold_in_rebalance_window():
    md = synthetic_market(date(2026, 10, 1))        # first trading day of the month
    sig = current.signals(md, PARAMS)
    assert sig["rebalance_window"] is True
    worst = sig["ranking"][-1]
    assert worst["momentum"] < 0
    held = [Position(isin=worst["isin"], name="w", quantity=3, price=50, value_eur=150)]
    orders = current.generate(state(cash=850, positions=held), md, PARAMS)
    assert orders[0].side == "sell" and orders[0].isin == worst["isin"]
    assert "negative" in orders[0].rationale


def test_outside_rebalance_window_losers_are_held():
    md = synthetic_market(date(2026, 10, 20))       # 14th trading day of the month
    sig = current.signals(md, PARAMS)
    assert sig["rebalance_window"] is False
    worst = sig["ranking"][-1]
    held = [Position(isin=worst["isin"], name="w", quantity=3, price=50, value_eur=150)]
    orders = current.generate(state(cash=850, positions=held), md, PARAMS)
    assert all(o.side == "buy" for o in orders)    # slots are filled, nothing is sold


def test_trend_band_holds_between_sma_and_exit_level():
    md = synthetic_market(date(2026, 10, 20))
    df = md.closes.copy()
    b = df[BENCH].to_numpy().copy()
    sma = pd.Series(b).rolling(PARAMS["trend"]["sma_days"]).mean().iloc[-1]
    b[-1] = sma * (1 - PARAMS["trend"]["exit_band"] / 2)   # below SMA, above the exit level
    df[BENCH] = b
    md2 = MarketData(closes=df, as_of=md.as_of, universe=md.universe)
    sig = current.signals(md2, PARAMS)
    assert sig["trend_on"] is False and sig["trend_exit"] is False
    held = [Position(isin="IE00B5BMR087", name="x", quantity=1.5, price=100, value_eur=150)]
    assert current.generate(state(cash=850, positions=held), md2, PARAMS) == []   # hold, no entries, no exits


def test_no_cash_means_no_buys():
    md = synthetic_market(date(2026, 10, 20))
    orders = current.generate(state(nav=1000, cash=20), md, PARAMS)
    assert orders == []


def test_full_book_holds():
    md = synthetic_market(date(2026, 10, 20))
    sig = current.signals(md, PARAMS)
    top4 = [r["isin"] for r in sig["ranking"][:4]]
    held = [Position(isin=i, name=i, quantity=1, price=250, value_eur=250) for i in top4]
    orders = current.generate(state(cash=0, positions=held), md, PARAMS)
    assert orders == []


def test_insufficient_history_means_no_ranking():
    md = synthetic_market(date(2026, 10, 20), n=100)
    sig = current.signals(md, PARAMS)
    assert sig["trend_on"] is False and sig["ranking"] == []
    assert current.generate(state(), md, PARAMS) == []
