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


def test_trend_on_buys_top_affordable_in_whole_shares_within_caps():
    md = synthetic_market(date(2026, 10, 20))
    orders = current.generate(state(), md, PARAMS)
    assert len(orders) == PARAMS["sizing"]["max_orders_per_day"]
    assert all(o.side == "buy" and o.eur_amount is None for o in orders)
    sig = current.signals(md, PARAMS)
    cap = 1000.0 * PARAMS["sizing"]["order_cap_pct_of_nav"]
    buffer = 1 + PARAMS["sizing"]["price_buffer"]
    affordable = [r["isin"] for r in sig["ranking"] if r["last_close"] * buffer <= cap]
    assert [o.isin for o in orders] == affordable[:2]
    close = {r["isin"]: r["last_close"] for r in sig["ranking"]}
    for o in orders:
        assert o.quantity >= 1 and float(o.quantity).is_integer()
        assert PARAMS["sizing"]["min_order_eur"] <= o.quantity * close[o.isin] * buffer <= cap
        assert (o.quantity + 1) * close[o.isin] * buffer > cap      # as many shares as fit
    assert all("rank" in o.rationale for o in orders)


def test_unaffordable_leaders_are_skipped_not_left_as_empty_slots():
    md = synthetic_market(date(2026, 10, 20))
    sig = current.signals(md, PARAMS)
    cap = 1000.0 * PARAMS["sizing"]["order_cap_pct_of_nav"]
    assert sig["ranking"][0]["last_close"] > cap      # the synthetic leader costs more than a slot
    orders = current.generate(state(), md, PARAMS)
    assert sig["ranking"][0]["isin"] not in {o.isin for o in orders}
    assert len(orders) == PARAMS["sizing"]["max_orders_per_day"]


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


def test_current_main_finds_dry_run_snapshot(repo, fake_sc, monkeypatch, capsys):
    """The daily session's entry point: snapshot --dry-run, then current.py, under
    FINANCE_DRY_RUN=1 and a replayed date. This is the path the first dry run broke."""
    import json as _json
    from finance import paths, portfolio
    from finance.clock import today
    md = synthetic_market(date(2026, 10, 20))
    u = data_mod.load_universe()
    isin_to_ticker = dict(zip(u["isin"], u["ticker"]))
    paths.PRICE_CACHE.mkdir(parents=True, exist_ok=True)
    md.closes.rename(columns=isin_to_ticker).to_csv(paths.PRICE_CACHE / "closes.csv")
    monkeypatch.setattr(data_mod, "CACHE", paths.PRICE_CACHE / "closes.csv")
    monkeypatch.setenv("FINANCE_DRY_RUN", "1")
    state, raw = portfolio.fetch_state(today(), dry_run=True)
    portfolio.write_snapshot(state, raw)
    assert current.main() == 0
    out = _json.loads(capsys.readouterr().out)
    assert out["state"]["dry_run"] is True and out["state"]["as_of"] == "2026-10-20"
    assert out["signals"]["trend_on"] is True
    assert len(out["proposed_orders"]) == PARAMS["sizing"]["max_orders_per_day"]


def test_daily_check_set_rotates_over_the_universe():
    from datetime import date, timedelta
    from strategy.data import DAILY_SLICE, daily_check_set
    isins = [f"X{i:02d}" for i in range(44)]
    seen = set()
    for d in range(6):
        day = date(2026, 10, 19) + timedelta(days=d)
        s = daily_check_set(isins, day, held=["X05"], benchmark="X00")
        assert s[:2] == ["X00", "X05"] and len(s) == 2 + DAILY_SLICE and len(set(s)) == len(s)
        seen |= set(s)
    assert seen == set(isins)
