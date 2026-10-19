#!/usr/bin/env python3
"""guardrails.py: the ONLY code path that may run `sc broker trade ... --confirm`.

    uv run python bin/guardrails.py validate trades/2026-10-20-01.json
    uv run python bin/guardrails.py execute  trades/2026-10-20-01.json [--dry-run]
    uv run python bin/guardrails.py attempted-today

Exit codes: 0 executed / dry-run ok / nothing to do (idempotent),
            2 rejected by a check, 3 aborted (CLI error, auth, halt),
            1 unexpected exception (never confirms).

The order of operations is fixed and every step writes its evidence into the trade
file before the next step runs:
  1. load mandate.toml fresh; refuse if HALTED exists
  2. validate the proposal against the mandate and today's portfolio snapshot
  3. run the `sc` phase-1 preview, store it raw, compare it with the proposal
  4. --dry-run stops here with status "dry_run"
  5. record `confirm_sent_at`, run phase 2 exactly once, store the result
A confirm is never retried. Running the script twice on a finished file does nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance import clock, mandate as mandate_mod, paths, portfolio, sc, trades  # noqa: E402

EXIT_OK, EXIT_BUG, EXIT_REJECTED, EXIT_ABORTED = 0, 1, 2, 3
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
SELL_VOLUME_TOLERANCE = 0.03   # sell preview volume vs quantity * our own quote


class Rejected(Exception):
    pass


class Aborted(Exception):
    pass


def _check(trade: dict, name: str, ok: bool, detail: str) -> None:
    trade.setdefault("checks", []).append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise Rejected(f"{name}: {detail}")


def _finish(path: Path, trade: dict, status: str, reason: str | None) -> None:
    trade["status"] = status
    trade["reason"] = reason
    trade["finished_at"] = trades.now_iso()
    trades.write(path, trade)


def _validate(trade: dict, man: mandate_mod.Mandate, today: date, *, dry_run: bool = False) -> tuple[portfolio.PortfolioState, dict]:
    lim = man.limits
    side, isin = trade.get("side"), str(trade.get("isin", "")).strip().upper()
    order_type = trade.get("order_type", "market")
    eur_amount = trade.get("eur_amount")
    quantity = trade.get("quantity")

    _check(trade, "halted", not paths.HALTED.exists(), "HALTED file present in repo root" if paths.HALTED.exists() else "no HALTED file")
    _check(trade, "side", side in ("buy", "sell"), f"side={side!r}")
    _check(trade, "isin_format", bool(ISIN_RE.match(isin)), f"isin={isin!r}")
    _check(trade, "order_type_allowed", order_type in lim.allowed_order_types(),
           f"order_type={order_type!r}, allowed={sorted(lim.allowed_order_types())}")
    if order_type == "limit":
        _check(trade, "limit_price", trade.get("limit_price") not in (None, 0), "limit order needs limit_price")
    _check(trade, "venue_configured", bool(man.venue), f"venue={man.venue!r}")
    _check(trade, "trading_day", man.is_trading_day(today), f"{today.isoformat()} is {'a' if man.is_trading_day(today) else 'not a'} trading day")

    attempted = trades.attempted_today(today)
    _check(trade, "orders_per_day", attempted < lim.max_orders_per_day,
           f"{attempted} attempted today, limit {lim.max_orders_per_day}")

    state = portfolio.latest_state(today, dry_run=dry_run)
    _check(trade, "snapshot_today", state is not None and state.as_of == today,
           "no portfolio snapshot for today; run bin/snapshot.py first" if state is None or state.as_of != today
           else f"snapshot {state.as_of.isoformat()} nav={state.nav:.2f} cash={state.cash:.2f}{(' DRY-RUN FIXTURE' if os.environ.get('FINANCE_SC_MODE') == 'fixture' else ' DRY-RUN') if state.dry_run else ''}")
    assert state is not None
    _check(trade, "nav_positive", state.nav > 0, f"nav={state.nav}")

    try:
        q = sc.quote(isin)
    except sc.ScError as exc:
        raise Aborted(f"quote failed: {exc}") from exc
    mid = sc.num(q.get("quote_mid_price"))
    _check(trade, "instrument_resolves", q.get("isin") == isin and mid is not None and mid > 0,
           f"quote isin={q.get('isin')} mid={mid} name={q.get('name')}")
    _check(trade, "quote_currency_eur", (q.get("quote_currency") or "EUR") == "EUR", f"currency={q.get('quote_currency')}")
    trade["quote"] = {k: q.get(k) for k in ("isin", "name", "security_type", "quote_mid_price", "quote_bid_price",
                                           "quote_ask_price", "quote_currency", "quote_timestamp_utc", "quote_is_outdated")}
    if not trade.get("name"):
        trade["name"] = q.get("name")

    max_order = lim.max_order_pct_of_nav * state.nav
    max_pos = lim.max_position_pct_of_nav * state.nav
    held = state.position(isin)
    held_qty = held.quantity if held else 0.0
    held_val = held.value_eur if held else 0.0

    if side == "buy":
        _check(trade, "buy_amount_or_quantity", (eur_amount is None) != (quantity is None), "buy needs exactly one of eur_amount, quantity")
        if quantity is not None:
            _check(trade, "buy_quantity_whole", float(quantity) > 0 and float(quantity).is_integer(), f"quantity={quantity} (buys by shares must be whole numbers)")
            est = float(quantity) * mid
        else:
            est = float(eur_amount)
        trade["estimated_eur"] = round(est, 2)
        _check(trade, "min_order", est >= lim.min_order_eur, f"{est:.2f} >= min {lim.min_order_eur:.2f}")
        _check(trade, "max_order_pct_of_nav", est <= max_order + 1e-6, f"{est:.2f} <= {lim.max_order_pct_of_nav:.0%} of NAV {state.nav:.2f} = {max_order:.2f}")
        _check(trade, "max_position_pct_of_nav", held_val + est <= max_pos + 1e-6,
               f"held {held_val:.2f} + order {est:.2f} <= {lim.max_position_pct_of_nav:.0%} of NAV = {max_pos:.2f}")
        spendable = state.buying_power - lim.cash_reserve_eur
        _check(trade, "cash_available", est <= spendable + 1e-6, f"{est:.2f} <= buying power {state.buying_power:.2f} - reserve {lim.cash_reserve_eur:.2f}")
    else:
        _check(trade, "sell_quantity", quantity is not None and float(quantity) > 0, f"quantity={quantity}")
        qty = float(quantity)
        _check(trade, "sell_holds_enough", held is not None and qty <= held_qty + 1e-9, f"sell {qty} <= held {held_qty}")
        est = qty * mid
        trade["estimated_eur"] = round(est, 2)
        whole = abs(qty - held_qty) < 1e-9
        _check(trade, "min_order", est >= lim.min_order_eur or whole,
               f"{est:.2f} >= min {lim.min_order_eur:.2f} (or whole position: {whole})")
    return state, q


def _compare_preview(trade: dict, data: dict, man: mandate_mod.Mandate, quote_mid: float) -> None:
    lim = man.limits
    result = data.get("result") if isinstance(data, dict) else None
    conf = data.get("confirmation") if isinstance(data, dict) else None
    _check(trade, "preview_shape", isinstance(result, dict) and isinstance(conf, dict) and bool(conf.get("id")),
           "preview has result and confirmation.id" if isinstance(result, dict) and isinstance(conf, dict) and conf.get("id") else "preview missing result/confirmation.id")
    intent = result.get("intent") or {}
    calc = result.get("calculation") or {}
    trad = result.get("tradability") or {}
    suit = result.get("suitability") or {}
    mq = result.get("market_quote") or {}
    side, isin = trade["side"], trade["isin"].upper()

    _check(trade, "preview_isin", str(intent.get("isin", "")).upper() == isin, f"preview isin={intent.get('isin')} proposal={isin}")
    _check(trade, "preview_side", (intent.get("side") or side) == side, f"preview side={intent.get('side')} proposal={side}")
    _check(trade, "preview_order_type", (intent.get("order_type") or "market") == trade.get("order_type", "market"),
           f"preview order_type={intent.get('order_type')} proposal={trade.get('order_type')}")
    _check(trade, "preview_currency", (mq.get("currency") or "EUR") == "EUR", f"currency={mq.get('currency')}")
    _check(trade, "preview_tradable", trad.get("tradable") is True and trad.get("status") != "NOT_TRADABLE",
           f"tradable={trad.get('tradable')} status={trad.get('status')} venue_status={trad.get('selected_venue_status')} reason={trad.get('selected_venue_unavailability_reason')}")
    if man.require_selected_venue_match:
        _check(trade, "preview_venue", str(trad.get("selected_venue", "")).upper() == man.venue.upper(),
               f"selected_venue={trad.get('selected_venue')} mandate={man.venue}")
    if lim.reject_on_appropriateness:
        needs = bool(trad.get("requires_appropriateness")) or bool(suit.get("questionnaire_required")) \
            or bool(suit.get("requires_appropriateness_warning_acknowledgement")) \
            or bool(conf.get("requires_appropriateness_warning_acknowledgement")) or result.get("warning") not in (None, {}, "")
        _check(trade, "preview_no_appropriateness", not needs,
               f"requires_appropriateness={trad.get('requires_appropriateness')} questionnaire={suit.get('questionnaire_required')} "
               f"ack={suit.get('requires_appropriateness_warning_acknowledgement')} warning={'present' if result.get('warning') else 'none'}")
    if lim.reject_on_price_warning:
        items = (result.get("price_warnings") or {}).get("items") or []
        _check(trade, "preview_no_price_warning", len(items) == 0, f"{len(items)} price warning(s)")

    vol = sc.num(calc.get("estimated_order_volume"))
    _check(trade, "preview_volume_present", vol is not None and vol > 0, f"estimated_order_volume={calc.get('estimated_order_volume')}")
    if side == "buy":
        if trade.get("eur_amount") is not None:
            want = float(trade["eur_amount"])
            _check(trade, "preview_amount_match", abs(vol - want) <= lim.preview_amount_tolerance * want,
                   f"preview volume {vol:.2f} vs proposal {want:.2f} (tolerance {lim.preview_amount_tolerance:.1%})")
        else:
            shares = sc.num(calc.get("shares"))
            _check(trade, "preview_shares_match", shares is not None and abs(shares - float(trade["quantity"])) < 1e-6,
                   f"preview shares {shares} vs proposal {trade['quantity']}")
            want = float(trade["quantity"]) * quote_mid
            _check(trade, "preview_amount_match", abs(vol - want) <= SELL_VOLUME_TOLERANCE * want,
                   f"preview volume {vol:.2f} vs quantity x quote {want:.2f} (tolerance {SELL_VOLUME_TOLERANCE:.0%})")
    else:
        shares = sc.num(calc.get("shares"))
        _check(trade, "preview_shares_match", shares is not None and abs(shares - float(trade["quantity"])) < 1e-6,
               f"preview shares {shares} vs proposal {trade['quantity']}")
        want = float(trade["quantity"]) * quote_mid
        _check(trade, "preview_amount_match", abs(vol - want) <= SELL_VOLUME_TOLERANCE * want,
               f"preview volume {vol:.2f} vs quantity x quote {want:.2f} (tolerance {SELL_VOLUME_TOLERANCE:.0%})")
    # Re-apply the hard caps to what the broker will actually execute.
    state_nav = float(trade.get("_nav", 0.0))
    if state_nav > 0 and side == "buy":
        _check(trade, "preview_max_order_pct", vol <= lim.max_order_pct_of_nav * state_nav + 1e-6,
               f"preview volume {vol:.2f} <= {lim.max_order_pct_of_nav:.0%} of NAV {state_nav:.2f}")
    exp = sc.num(conf.get("expires_at_epoch"))
    _check(trade, "preview_not_expired", exp is not None and exp > time.time() + 30,
           f"confirmation expires at epoch {exp}, now {int(time.time())}")


def execute(path: Path, *, dry_run: bool) -> int:
    trade = trades.load(path)
    status = trade.get("status")
    if status != trades.STATUS_PROPOSED:
        print(json.dumps({"id": trade.get("id", path.stem), "status": status, "note": "nothing to do (idempotent)"}))
        return EXIT_OK
    if os.environ.get("FINANCE_DRY_RUN") == "1" and not dry_run:
        _finish(path, trade, trades.STATUS_ABORTED, "FINANCE_DRY_RUN=1 in the environment but execute was called without --dry-run")
        print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"]}))
        return EXIT_ABORTED

    today = clock.today()
    trade["dry_run"] = bool(dry_run)
    man = mandate_mod.load()
    trade["mandate_snapshot"] = {"limits": man.raw.get("limits"), "venue": man.raw.get("venue")}
    try:
        state, q = _validate(trade, man, today, dry_run=dry_run)
        trade["_nav"] = state.nav
        args = sc.trade_args(trade["side"], trade["isin"].upper(), eur_amount=trade.get("eur_amount"),
                             quantity=trade.get("quantity"), order_type=trade.get("order_type", "market"),
                             limit_price=trade.get("limit_price"), stop_price=trade.get("stop_price"),
                             venue=man.venue or None)
        trade["attempt"] = {"preview_args": args, "previewed_at": trades.now_iso()}
        trades.write(path, trade)
        try:
            preview = sc.trade_preview(args)
        except sc.ScError as exc:
            trade["preview_error"] = exc.to_dict()
            raise Aborted(f"preview failed: {exc}") from exc
        trade["preview"] = preview.data
        trades.write(path, trade)
        _compare_preview(trade, preview.data, man, float(sc.num(q.get("quote_mid_price")) or 0.0))
        conf_id = preview.data["confirmation"]["id"]
        trade["attempt"].update({"confirmation_id": conf_id,
                                 "expires_at_epoch": preview.data["confirmation"].get("expires_at_epoch")})
        trade.pop("_nav", None)
        if dry_run:
            _finish(path, trade, trades.STATUS_DRY_RUN, "dry run: preview matched, confirm deliberately skipped")
            print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"],
                              "estimated_order_volume": (trade["preview"].get("result") or {}).get("calculation", {}).get("estimated_order_volume")}))
            return EXIT_OK

        # ---- the one and only confirm ----
        confirm_args = [*args, "--confirm", conf_id]
        trade["attempt"]["confirm_args"] = confirm_args
        trade["attempt"]["confirm_sent_at"] = trades.now_iso()
        trades.write(path, trade)   # evidence on disk before the call
        try:
            result = sc.trade_confirm(confirm_args)
        except sc.ScError as exc:
            trade["confirm_error"] = exc.to_dict()
            msg = str(exc)
            if exc.exit_code == sc.EXIT_VALIDATION and "CONFIRMATION_" in msg:
                _finish(path, trade, trades.STATUS_ABORTED, f"confirm refused before submission: {msg}")
                print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"]}))
                return EXIT_ABORTED
            _finish(path, trade, trades.STATUS_UNKNOWN,
                    f"confirm was sent but the CLI returned an error; outcome unknown, NEVER retry. "
                    f"Check `sc broker transactions --isin {trade['isin']}`. Error: {msg}")
            print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"]}))
            return EXIT_ABORTED
        trade["confirm"] = result.data
        sub = ((result.data or {}).get("result") or {}).get("order_submission") or {}
        order_id = sub.get("order_id")
        if sub.get("submitted") is True and order_id:
            trade["order_id"] = order_id
            trade["fill"] = {"is_marketable": sub.get("is_marketable"), "idempotency_reused": sub.get("idempotency_reused")}
            _finish(path, trade, trades.STATUS_EXECUTED, "order submitted")
            print(json.dumps({"id": trade["id"], "status": trade["status"], "order_id": order_id}))
            return EXIT_OK
        _finish(path, trade, trades.STATUS_UNKNOWN,
                "confirm returned ok but no submitted order_id; outcome unknown, NEVER retry. Check `sc broker transactions`.")
        print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"]}))
        return EXIT_ABORTED

    except Rejected as exc:
        trade.pop("_nav", None)
        _finish(path, trade, trades.STATUS_REJECTED, str(exc))
        print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"]}))
        return EXIT_REJECTED
    except Aborted as exc:
        trade.pop("_nav", None)
        _finish(path, trade, trades.STATUS_ABORTED, str(exc))
        print(json.dumps({"id": trade["id"], "status": trade["status"], "reason": trade["reason"]}))
        return EXIT_ABORTED
    except Exception as exc:  # noqa: BLE001  - any bug: record, never confirm
        trade.pop("_nav", None)
        trade["exception"] = traceback.format_exc()[-4000:]
        _finish(path, trade, trades.STATUS_ABORTED, f"unexpected error: {exc!r}")
        print(json.dumps({"id": trade.get("id", path.stem), "status": trade["status"], "reason": trade["reason"]}))
        return EXIT_BUG


def validate_only(path: Path) -> int:
    """Run the pre-preview checks and print them. Does not write the trade file."""
    trade = trades.load(path)
    man = mandate_mod.load()
    try:
        _validate(trade, man, clock.today(), dry_run=bool(trade.get("dry_run")))
        ok = True
    except Rejected as exc:
        ok = False
        trade["reason"] = str(exc)
    except Aborted as exc:
        ok = False
        trade["reason"] = f"aborted: {exc}"
    print(json.dumps({"id": trade.get("id", path.stem), "valid": ok, "reason": trade.get("reason"), "checks": trade.get("checks", [])}, indent=2))
    return EXIT_OK if ok else EXIT_REJECTED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_val = sub.add_parser("validate", help="run the mandate checks only")
    p_val.add_argument("trade_file", type=Path)
    p_exe = sub.add_parser("execute", help="validate, preview, compare, confirm")
    p_exe.add_argument("trade_file", type=Path)
    p_exe.add_argument("--dry-run", action="store_true", help="stop after the preview; never confirm")
    sub.add_parser("attempted-today", help="print how many orders were attempted today")
    args = ap.parse_args(argv)
    if args.cmd == "attempted-today":
        print(json.dumps({"date": clock.today().isoformat(), "attempted": trades.attempted_today(clock.today())}))
        return EXIT_OK
    path: Path = args.trade_file
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        print(json.dumps({"error": f"no such trade file: {path}"}))
        return EXIT_BUG
    if paths.TRADES.resolve() not in path.parents:
        print(json.dumps({"error": f"trade file must live under {paths.TRADES}"}))
        return EXIT_BUG
    if args.cmd == "validate":
        return validate_only(path)
    return execute(path, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
