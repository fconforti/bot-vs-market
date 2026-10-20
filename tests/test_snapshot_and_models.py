from __future__ import annotations

import json
from datetime import date

from finance import portfolio, trades
from finance.models import PortfolioState


def test_fetch_state_from_fixture(repo, fake_sc):
    state, raw = portfolio.fetch_state(date(2026, 10, 20))
    assert state.nav == 1000.0
    assert state.cash == 775.32
    assert len(state.positions) == 1
    p = state.positions[0]
    assert p.isin == "IE00B4L5Y983" and p.quantity == 2 and p.value_eur == 224.68
    assert raw["reconciliation_gap_eur"] == 0.0


def test_snapshot_roundtrip(repo, fake_sc):
    state, raw = portfolio.fetch_state(date(2026, 10, 20))
    path = portfolio.write_snapshot(state, raw)
    loaded = portfolio.load_snapshot(path)
    assert loaded == state
    assert portfolio.latest_state(date(2026, 10, 20)) == state
    post = portfolio.write_snapshot(state, raw, post_trade=True)
    assert post.name.endswith(".post.json")
    assert portfolio.list_snapshots() == [path]


def test_dry_run_snapshots_excluded_from_equity_curve(repo, fake_sc):
    state, raw = portfolio.fetch_state(date(2026, 10, 20), dry_run=True)
    portfolio.write_snapshot(state, raw)
    assert portfolio.equity_curve() == []


def test_benchmark_units_fixed_on_first_live_day(repo):
    closes = {"2026-10-19": 100.0, "2026-10-20": 110.0, "2026-10-21": 121.0}
    b = portfolio.update_benchmark(isin="X", name="X", initial_eur=1000.0, closes=closes, start_date=date(2026, 10, 20))
    assert b["units"] == 1000.0 / 110.0
    assert [r["value"] for r in b["series"]] == [1000.0, 1100.0]
    portfolio.save_benchmark(b)
    b3 = portfolio.update_benchmark(isin="X", name="X", initial_eur=1000.0, closes={"2026-10-22": 99.0}, start_date=date(2026, 10, 20))
    assert b3["units"] == b["units"] and b3["series"][-1]["value"] == 900.0


def test_trade_numbering_and_attempt_count(repo):
    d = date(2026, 10, 20)
    p1 = trades.new_proposal(day=d, isin="IE00B5BMR087", side="buy", eur_amount=100)
    p2 = trades.new_proposal(day=d, isin="IE00B5BMR087", side="buy", eur_amount=100)
    assert p1.name == "2026-10-20-01.json" and p2.name == "2026-10-20-02.json"
    assert trades.attempted_today(d) == 0
    t = trades.load(p1)
    t["status"] = "executed"
    trades.write(p1, t)
    assert trades.attempted_today(d) == 1


def test_dry_run_attempts_do_not_count_against_live_limit(repo):
    d = date(2026, 10, 20)
    p = trades.new_proposal(day=d, isin="IE00B5BMR087", side="buy", quantity=2, dry_run=True)
    t = trades.load(p)
    t["status"] = "aborted"
    trades.write(p, t)
    assert trades.attempted_today(d) == 0


def test_snapshot_raw_payloads_are_redacted(repo):
    import json
    from finance import portfolio
    from finance.models import PortfolioState
    state = PortfolioState(as_of=date(2026, 10, 20), nav=1000.0, cash=1000.0, buying_power=1000.0, positions=())
    raw = {"holdings": {"items": [{"doc": "https://x.example/kid.pdf?apiKey=SECRET1&lang=it", "access_token": "SECRET2"}]}}
    text = portfolio.write_snapshot(state, raw).read_text()
    assert "SECRET1" not in text and "SECRET2" not in text
    assert json.loads(text)["raw"]["holdings"]["items"][0]["doc"].endswith("apiKey=[redacted]&lang=it")


def test_benchmark_series_may_only_grow():
    import importlib.util
    from finance import paths
    spec = importlib.util.spec_from_file_location("check_append_only", paths.ROOT / "bin" / "check-append-only.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    empty = {"isin": "X", "initial_eur": 1000.0, "start_date": None, "units": None, "series": []}
    day1 = {"isin": "X", "initial_eur": 1000.0, "start_date": "2026-10-20", "units": 7.6, "start_close": 130.4,
            "series": [{"date": "2026-10-20", "close": 130.4, "value": 1000.0}]}
    day2 = {**day1, "series": day1["series"] + [{"date": "2026-10-21", "close": 131.0, "value": 1004.6}]}
    assert mod.series_grows(None, day1) is None          # new file
    assert mod.series_grows(empty, day1) is None         # first live run fixes the units
    assert mod.series_grows(day1, day2) is None          # a day appended
    assert mod.series_grows(day1, {**day1, "units": 8.0})
    assert mod.series_grows(day2, day1)                  # a point dropped
    changed = {**day2, "series": [{**day2["series"][0], "close": 1.0}, day2["series"][1]]}
    assert mod.series_grows(day2, changed)               # a point rewritten
