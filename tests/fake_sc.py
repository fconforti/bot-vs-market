#!/usr/bin/env python3
"""A stand-in for the `sc` binary. Serves JSON fixtures from $FINANCE_SC_FIXTURES.

Used by the unit tests and by `bin/run-session.sh --dry-run` when the real CLI is
not logged in. It never talks to the network.

Lookup: the leading non-flag tokens form a key (e.g. `broker.trade.buy`); with
`--confirm` the key gets `.confirm`. Files tried in order:
  <key>.<ISIN>.json, <key>.json
A fixture may carry `"_exit": <code>` to simulate a failure exit code. Trade and
quote fixtures are templates: amount/shares/estimated volume are filled from the
arguments and from prices.json ({isin: mid_price}).
Every call is appended to $FINANCE_SC_CALLLOG (one JSON line) when set.
"""
import json
import os
import sys
import time
from pathlib import Path


def main(argv):
    fixtures = Path(os.environ.get("FINANCE_SC_FIXTURES", ""))
    log = os.environ.get("FINANCE_SC_CALLLOG")
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"argv": argv, "t": time.time()}) + "\n")
    flags = {}
    key_parts = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                flags[a[2:]] = argv[i + 1]
                i += 2
            else:
                flags[a[2:]] = True
                i += 1
        else:
            if not flags:
                key_parts.append(a)
            i += 1
    key = ".".join(key_parts)
    if "confirm" in flags:
        key += ".confirm"
    isin = flags.get("isin")
    candidates = []
    if isin:
        candidates.append(fixtures / f"{key}.{isin}.json")
    candidates.append(fixtures / f"{key}.json")
    path = next((c for c in candidates if c.exists()), None)
    if path is None:
        print(json.dumps({"ok": False, "command": key, "error": {"code": "validation_error",
                          "message": f"fake sc: no fixture for {key} in {fixtures}"}}))
        return 10
    env = json.loads(path.read_text(encoding="utf-8"))
    exit_code = int(env.pop("_exit", 0))

    prices = {}
    pfile = fixtures / "prices.json"
    if pfile.exists():
        prices = json.loads(pfile.read_text(encoding="utf-8"))
    mid = float(prices.get(isin, 100.0)) if isin else None

    data = env.get("data")
    if isinstance(data, dict) and key.startswith("broker.quote") and isin:
        q = data["result"]
        q["isin"] = isin
        q["quote_mid_price"] = f"{mid:.4f}"
        q["quote_bid_price"] = f"{mid * 0.999:.4f}"
        q["quote_ask_price"] = f"{mid * 1.001:.4f}"
    if isinstance(data, dict) and key.startswith("broker.trade.") and isin and "result" in data:
        res = data["result"]
        intent = res.setdefault("intent", {})
        intent["isin"] = isin
        intent["order_type"] = flags.get("order-type", "market")
        intent["venue_override"] = flags.get("venue")
        side = "sell" if ".sell" in key else "buy"
        intent["side"] = side
        ask, bid = mid * 1.001, mid * 0.999
        if side == "buy" and "amount" in flags:
            amount = float(flags["amount"])
            shares = amount / ask
            intent["amount"] = flags["amount"]
            intent["shares"] = None
        else:
            shares = float(flags.get("shares", 0))
            intent["shares"] = flags.get("shares")
            intent["amount"] = None
        price = ask if side == "buy" else bid
        vol = shares * price
        res.setdefault("calculation", {})
        res["calculation"].update({"shares": f"{shares:.6f}", "estimated_order_volume_raw": f"{vol:.4f}",
                                   "estimated_order_volume": f"{vol:.4f}", "sizing_price": f"{price:.4f}"})
        res.setdefault("market_quote", {}).update({"mid_price": f"{mid:.4f}", "ask_price": f"{ask:.4f}",
                                                   "bid_price": f"{bid:.4f}", "currency": "EUR"})
        trad = res.setdefault("tradability", {})
        if flags.get("venue"):
            trad["selected_venue"] = flags["venue"]
        conf = data.setdefault("confirmation", {})
        if "confirm" in flags:
            conf["id"] = flags["confirm"]
            conf["consumed"] = True
        else:
            conf.setdefault("id", "fake-confirmation-id")
            conf["expires_at_epoch"] = int(time.time()) + 900
    override = env.pop("_override", None)
    if isinstance(override, dict):
        _deep_merge(env, override)
    sys.stdout.write(json.dumps(env, separators=(",", ":")) + "\n")
    return exit_code


def _deep_merge(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
