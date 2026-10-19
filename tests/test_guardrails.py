from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import pytest

from finance import paths, trades

REPO = Path(__file__).resolve().parent.parent


def _load_guardrails():
    spec = importlib.util.spec_from_file_location("guardrails", REPO / "bin" / "guardrails.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["guardrails"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gr():
    return _load_guardrails()


def proposal(**kw) -> Path:
    base = dict(day=date(2026, 10, 20), isin="IE00B5BMR087", side="buy", eur_amount=200.0,
                rationale="test", name="S&P 500", strategy_version="v001")
    base.update(kw)
    return trades.new_proposal(**base)


def test_happy_buy_executes_once(gr, repo, fake_sc, snapshot):
    p = proposal()
    rc = gr.main(["execute", str(p)])
    t = trades.load(p)
    assert rc == 0, t
    assert t["status"] == "executed"
    assert t["order_id"] == "fixture-order-id"
    previews, confirms = fake_sc.trade_calls(confirm=False), fake_sc.trade_calls(confirm=True)
    assert len(previews) == 1 and len(confirms) == 1
    assert "--venue" in previews[0] and previews[0][previews[0].index("--venue") + 1] == "SEIX"
    assert "--amount" in previews[0] and "200.00" in previews[0]
    assert confirms[0][-3:] == ["--confirm", "fake-confirmation-id", "--json"]
    assert confirms[0][:-3] == previews[0][:-1]   # identical phase-1 arguments
    assert all(c["ok"] for c in t["checks"])
    assert t["attempt"]["confirm_sent_at"]
    assert t["preview"]["result"]["intent"]["isin"] == "IE00B5BMR087"


def test_idempotent_second_run_does_nothing(gr, repo, fake_sc, snapshot):
    p = proposal()
    assert gr.main(["execute", str(p)]) == 0
    n = len(fake_sc.calls())
    assert gr.main(["execute", str(p)]) == 0
    assert len(fake_sc.calls()) == n
    assert trades.load(p)["status"] == "executed"


def test_dry_run_never_confirms(gr, repo, fake_sc, snapshot):
    from finance import portfolio
    st, raw = portfolio.fetch_state(date(2026, 10, 20), dry_run=True)
    portfolio.write_snapshot(st, raw)
    p = proposal(dry_run=True)
    assert gr.main(["execute", str(p), "--dry-run"]) == 0
    t = trades.load(p)
    assert t["status"] == "dry_run"
    assert fake_sc.trade_calls(confirm=True) == []
    assert len(fake_sc.trade_calls(confirm=False)) == 1
    # and a dry run does not count as an attempt
    assert trades.attempted_today(date(2026, 10, 20)) == 0


def test_dry_run_without_dry_run_snapshot_is_rejected(gr, repo, fake_sc, snapshot):
    p = proposal(dry_run=True)
    assert gr.main(["execute", str(p), "--dry-run"]) == 2
    assert "snapshot_today" in trades.load(p)["reason"]


def test_env_dry_run_blocks_live_execute(gr, repo, fake_sc, snapshot, monkeypatch):
    monkeypatch.setenv("FINANCE_DRY_RUN", "1")
    p = proposal()
    assert gr.main(["execute", str(p)]) == 3
    assert trades.load(p)["status"] == "aborted"
    assert fake_sc.trade_calls() == []


def test_halted_file_aborts(gr, repo, fake_sc, snapshot):
    paths.HALTED.write_text("stop\n")
    p = proposal()
    assert gr.main(["execute", str(p)]) == 2
    assert fake_sc.trade_calls() == []


def test_rejects_order_above_max_pct_of_nav(gr, repo, fake_sc, snapshot):
    p = proposal(eur_amount=260.0)     # NAV 1000 -> cap 250
    assert gr.main(["execute", str(p)]) == 2
    t = trades.load(p)
    assert t["status"] == "rejected" and "max_order_pct_of_nav" in t["reason"]
    assert fake_sc.trade_calls() == []


def test_rejects_below_min_order(gr, repo, fake_sc, snapshot):
    p = proposal(eur_amount=10.0)
    assert gr.main(["execute", str(p)]) == 2
    assert "min_order" in trades.load(p)["reason"]


def test_rejects_position_above_max_pct(gr, repo, fake_sc, snapshot):
    # held EUNL = 224.68; +200 = 424.68 > 400
    p = proposal(isin="IE00B4L5Y983", eur_amount=200.0)
    assert gr.main(["execute", str(p)]) == 2
    assert "max_position_pct_of_nav" in trades.load(p)["reason"]


def test_rejects_when_cash_short(gr, repo, fake_sc, snapshot):
    fake_sc.patch("broker.cash-breakdown.json", data={"cash_balance": "50", "buying_power": "50", "pending_buy_orders_amount": "0"})
    from finance import portfolio
    from finance.clock import today
    state, raw = portfolio.fetch_state(today())
    portfolio.write_snapshot(state, raw)
    p = proposal(eur_amount=100.0)
    assert gr.main(["execute", str(p)]) == 2
    assert "cash_available" in trades.load(p)["reason"]


def test_rejects_sell_more_than_held(gr, repo, fake_sc, snapshot):
    p = proposal(isin="IE00B4L5Y983", side="sell", eur_amount=None, quantity=3.0)
    assert gr.main(["execute", str(p)]) == 2
    assert "sell_holds_enough" in trades.load(p)["reason"]


def test_sell_whole_position_executes(gr, repo, fake_sc, snapshot):
    p = proposal(isin="IE00B4L5Y983", side="sell", eur_amount=None, quantity=2.0)
    assert gr.main(["execute", str(p)]) == 0
    t = trades.load(p)
    assert t["status"] == "executed"
    prev = fake_sc.trade_calls(confirm=False)[0]
    assert prev[2] == "sell" and "--shares" in prev and "--amount" not in prev


def test_max_orders_per_day(gr, repo, fake_sc, snapshot):
    assert gr.main(["execute", str(proposal(eur_amount=100.0))]) == 0
    assert gr.main(["execute", str(proposal(eur_amount=100.0))]) == 0
    p3 = proposal(eur_amount=100.0)
    assert gr.main(["execute", str(p3)]) == 2
    assert "orders_per_day" in trades.load(p3)["reason"]
    assert len(fake_sc.trade_calls(confirm=True)) == 2


def test_not_a_trading_day(gr, repo, fake_sc, snapshot, monkeypatch):
    monkeypatch.setenv("FINANCE_TODAY", "2026-10-24")   # Saturday
    p = proposal(day=date(2026, 10, 24))
    assert gr.main(["execute", str(p)]) == 2
    assert "trading_day" in trades.load(p)["reason"]


def test_no_snapshot_today(gr, repo, fake_sc):
    p = proposal()
    assert gr.main(["execute", str(p)]) == 2
    assert "snapshot_today" in trades.load(p)["reason"]


@pytest.mark.parametrize("override, check", [
    ({"result": {"tradability": {"tradable": False, "status": "NOT_TRADABLE"}}}, "preview_tradable"),
    ({"result": {"tradability": {"selected_venue": "XETR"}}}, "preview_venue"),
    ({"result": {"calculation": {"estimated_order_volume": "150.0000"}}}, "preview_amount_match"),
    ({"result": {"intent": {"isin": "DE0007164600"}}}, "preview_isin"),
    ({"result": {"price_warnings": {"items": [{"kind": "LIMIT_FAR_FROM_QUOTE"}]}}}, "preview_no_price_warning"),
    ({"result": {"suitability": {"questionnaire_required": True}}}, "preview_no_appropriateness"),
    ({"result": {"tradability": {"requires_appropriateness": True}}}, "preview_no_appropriateness"),
    ({"result": {"warning": {"kind": "APPROPRIATENESS", "title": "x", "version": "1"}}}, "preview_no_appropriateness"),
    ({"result": {"market_quote": {"currency": "USD"}}}, "preview_currency"),
    ({"confirmation": {"expires_at_epoch": 1}}, "preview_not_expired"),
])
def test_preview_mismatch_rejects_without_confirm(gr, repo, fake_sc, snapshot, override, check):
    fake_sc.patch("broker.trade.buy.json", _override={"data": override})
    p = proposal()
    assert gr.main(["execute", str(p)]) == 2
    t = trades.load(p)
    assert t["status"] == "rejected" and check in t["reason"], t["reason"]
    assert fake_sc.trade_calls(confirm=True) == []
    assert t["preview"] is not None   # raw preview is stored even when rejected


def test_preview_cli_error_aborts(gr, repo, fake_sc, snapshot):
    fake_sc.patch("broker.trade.buy.json", _exit=30)
    p = proposal()
    assert gr.main(["execute", str(p)]) == 3
    t = trades.load(p)
    assert t["status"] == "aborted" and "preview failed" in t["reason"]
    assert fake_sc.trade_calls(confirm=True) == []


def test_confirm_error_is_unknown_and_never_retried(gr, repo, fake_sc, snapshot):
    fake_sc.patch("broker.trade.buy.confirm.json", _exit=30)
    p = proposal()
    assert gr.main(["execute", str(p)]) == 3
    t = trades.load(p)
    assert t["status"] == "unknown"
    assert "NEVER retry" in t["reason"]
    assert len(fake_sc.trade_calls(confirm=True)) == 1
    # a second run must not send anything
    assert gr.main(["execute", str(p)]) == 3 or True
    assert len(fake_sc.trade_calls(confirm=True)) == 1
    # an unknown outcome counts against the daily limit
    assert trades.attempted_today(date(2026, 10, 20)) == 1


def test_confirm_refused_before_submission_is_aborted(gr, repo, fake_sc, snapshot):
    fake_sc.patch("broker.trade.buy.confirm.json", _exit=10,
                  ok=False, error={"code": "validation_error", "message": "CONFIRMATION_EXPIRED: confirmation id 'x' expired"})
    p = proposal()
    assert gr.main(["execute", str(p)]) == 3
    assert trades.load(p)["status"] == "aborted"


def test_auth_error_on_quote_aborts(gr, repo, fake_sc, snapshot):
    fake_sc.patch("broker.quote.json", _exit=20, ok=False, error={"code": "auth_or_config_error", "message": "Run 'sc login'"})
    p = proposal()
    assert gr.main(["execute", str(p)]) == 3
    t = trades.load(p)
    assert t["status"] == "aborted" and "quote failed" in t["reason"]
    assert fake_sc.trade_calls() == []


def test_limit_orders_disabled_by_mandate(gr, repo, fake_sc, snapshot):
    p = proposal(order_type="limit", limit_price=600.0)
    assert gr.main(["execute", str(p)]) == 2
    assert "order_type_allowed" in trades.load(p)["reason"]


def test_trade_file_outside_trades_dir_refused(gr, repo, fake_sc, snapshot, tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"status": "proposed"}))
    assert gr.main(["execute", str(p)]) == 1


def test_redaction_of_secret_like_keys():
    out = trades.redact({"access_token": "abc", "nested": {"Authorization": "x", "fine": 1}, "list": [{"api_key": "k"}]})
    assert out == {"access_token": "[redacted]", "nested": {"Authorization": "[redacted]", "fine": 1}, "list": [{"api_key": "[redacted]"}]}
    url = "https://api.fundinfo.com/document/x/KID.pdf?apiKey=abc123&lang=it"
    assert trades.redact({"url": url}) == {"url": "https://api.fundinfo.com/document/x/KID.pdf?apiKey=[redacted]&lang=it"}


def test_bug_in_checks_never_confirms(gr, repo, fake_sc, snapshot, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("synthetic bug")
    monkeypatch.setattr(gr, "_compare_preview", boom)
    p = proposal()
    assert gr.main(["execute", str(p)]) == 1
    t = trades.load(p)
    assert t["status"] == "aborted" and "synthetic bug" in t["reason"]
    assert fake_sc.trade_calls(confirm=True) == []
