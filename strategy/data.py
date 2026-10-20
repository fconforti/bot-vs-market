"""Price data for the strategy.

- Daily closes come from yfinance for every instrument in strategy/universe.csv. All
  tickers are EUR listings (Xetra `.DE`, Paris `.PA`) so no FX conversion is needed.
- A local cache under data/prices/ (gitignored) avoids re-downloading history.
- `--refresh` is what the daily session runs. It downloads the last weeks, reports
  stale or missing instruments and cross-checks held positions against live `sc`
  quotes when the CLI is logged in.

Usage:
    uv run python strategy/data.py --refresh            # daily
    uv run python strategy/data.py --full               # rebuild the whole cache
    uv run python strategy/data.py --check-live         # holdings, benchmark, rotating slice
    uv run python strategy/data.py --check-live --all   # every instrument (one-off, slow)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finance import paths, sc  # noqa: E402
from finance.models import MarketData  # noqa: E402

UNIVERSE_CSV = Path(__file__).resolve().parent / "universe.csv"
CACHE = paths.PRICE_CACHE / "closes.csv"
META = paths.PRICE_CACHE / "meta.json"
HISTORY_START = "2012-01-01"


def load_universe() -> pd.DataFrame:
    u = pd.read_csv(UNIVERSE_CSV, dtype=str).fillna("")
    u["prime"] = u["prime"].str.lower().isin(["true", "1", "yes"])
    u["isin"] = u["isin"].str.strip().str.upper()
    u["ticker"] = u["ticker"].str.strip()
    return u


def _download(tickers: list[str], start: str, end: str | None = None) -> pd.DataFrame:
    import yfinance as yf  # imported lazily: slow and network-bound

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False,
                          group_by="column", threads=True)
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", axis=1, level=0)
    else:
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    return closes.sort_index()


def load_cache() -> pd.DataFrame:
    if not CACHE.exists():
        return pd.DataFrame()
    df = pd.read_csv(CACHE, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).normalize()
    return df.sort_index()


def save_cache(df: pd.DataFrame, note: dict | None = None) -> None:
    paths.PRICE_CACHE.mkdir(parents=True, exist_ok=True)
    df.sort_index().to_csv(CACHE, float_format="%.6f")
    meta = {"updated_at": datetime.now(timezone.utc).isoformat(), "rows": int(len(df)),
            "columns": int(df.shape[1]), **(note or {})}
    META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


# Xetra closes at 17:30 CET. A bar for today fetched before this is an intraday price.
CLOSE_FINAL_AFTER = time(17, 45)
XETRA_TZ = ZoneInfo("Europe/Berlin")


def drop_unfinished(fresh: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Remove today's bar when the session has not closed yet (2026-10-19: a 16:40
    refresh stored an intraday price as that day's close, and it stayed)."""
    local = now.astimezone(XETRA_TZ)
    if fresh.empty or local.time() >= CLOSE_FINAL_AFTER:
        return fresh
    return fresh[fresh.index.date < local.date()]


def merge_window(fresh: pd.DataFrame, cached: pd.DataFrame) -> pd.DataFrame:
    """Fresh data is authoritative inside its own window: a cached date it no longer
    contains is dropped rather than kept, so a provisional bar cannot outlive the
    source. Inside fresh dates, cached values still fill cells fresh lacks."""
    if cached.empty:
        return fresh
    if fresh.empty:
        return cached
    keep = (cached.index < fresh.index.min()) | cached.index.isin(fresh.index)
    return fresh.combine_first(cached[keep])


def fill_from_hourly(fresh: pd.DataFrame, hourly: pd.DataFrame, days: list[date]) -> tuple[pd.DataFrame, list[str]]:
    """Yahoo's daily series sometimes lags a completed day (2026-10-20: no 10-19 bar)
    while its hourly series has it. For each given day missing from `fresh`, take the
    close of the last hourly bar that starts at 17:00 Berlin or later (it ends at the
    Xetra close). `hourly` is indexed by tz-aware timestamps."""
    filled = []
    if hourly.empty:
        return fresh, filled
    h = hourly.copy()
    h.index = h.index.tz_convert(XETRA_TZ)
    rows = {}
    for d in days:
        if pd.Timestamp(d) in fresh.index:
            continue
        bars = h[(h.index.date == d) & (h.index.time >= time(17, 0))]
        if bars.empty:
            continue
        rows[pd.Timestamp(d)] = bars.iloc[-1]
        filled.append(d.isoformat())
    if not rows:
        return fresh, filled
    extra = pd.DataFrame.from_dict(rows, orient="index").reindex(columns=fresh.columns)
    return pd.concat([fresh, extra]).sort_index(), filled


def _download_hourly(tickers: list[str], days: int = 7) -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = yf.download(tickers, period=f"{days}d", interval="60m", auto_adjust=True, progress=False,
                          group_by="column", threads=True)
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        return raw["Close"]
    return raw[["Close"]].rename(columns={"Close": tickers[0]})


def _completed_trading_days(since: date, now: datetime) -> list[date]:
    from finance import mandate
    man = mandate.load()
    local = now.astimezone(XETRA_TZ)
    last = local.date() if local.time() >= CLOSE_FINAL_AFTER else local.date() - timedelta(days=1)
    out, d = [], since
    while d <= last:
        if man.is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def refresh(*, full: bool = False, lookback_days: int = 30, now: datetime | None = None) -> tuple[pd.DataFrame, dict]:
    """Update the close cache. Returns (closes by ticker, report)."""
    now = now or datetime.now(timezone.utc)
    u = load_universe()
    tickers = sorted(set(u["ticker"]))
    cached = pd.DataFrame() if full else load_cache()
    if cached.empty:
        start = HISTORY_START
    else:
        start = (cached.index.max() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    fresh = drop_unfinished(_download(tickers, start), now)
    if fresh.empty and cached.empty:
        raise RuntimeError("yfinance returned no data; check network and tickers")
    # Completed trading days of the last week that the daily series does not have yet.
    recent = [d for d in _completed_trading_days(now.date() - timedelta(days=7), now)
              if pd.Timestamp(d) not in fresh.index]
    filled: list[str] = []
    if recent:
        try:
            fresh, filled = fill_from_hourly(fresh, _download_hourly(tickers), recent)
        except Exception as exc:  # network or yfinance shape: report, do not guess
            filled = [f"hourly fill failed: {exc}"]
    merged = merge_window(fresh, cached)
    merged = merged.reindex(columns=tickers)
    merged = merged.dropna(how="all")
    report = {
        "as_of": merged.index.max().strftime("%Y-%m-%d") if len(merged) else None,
        "missing": [t for t in tickers if t not in fresh.columns or fresh[t].dropna().empty],
        "stale": [],
        "filled_from_hourly": filled,
        "missing_days": [d.isoformat() for d in recent if pd.Timestamp(d) not in merged.index],
    }
    last_date = merged.index.max()
    for t in tickers:
        s = merged[t].dropna() if t in merged else pd.Series(dtype=float)
        if s.empty:
            continue
        if (last_date - s.index.max()).days > 5:
            report["stale"].append({"ticker": t, "last": s.index.max().strftime("%Y-%m-%d")})
    save_cache(merged, {"last_refresh_report": report})
    return merged, report


def closes_by_isin(closes_by_ticker: pd.DataFrame | None = None) -> pd.DataFrame:
    u = load_universe()
    df = closes_by_ticker if closes_by_ticker is not None else load_cache()
    mapping = {row.ticker: row.isin for row in u.itertuples()}
    cols = [t for t in df.columns if t in mapping]
    out = df[cols].rename(columns=mapping)
    return out.loc[:, ~out.columns.duplicated()]


def market_data(as_of: date | None = None) -> MarketData:
    closes = closes_by_isin()
    if closes.empty:
        raise RuntimeError("price cache is empty; run `uv run python strategy/data.py --full`")
    as_of = as_of or closes.index.max().date()
    return MarketData(closes=closes, as_of=as_of, universe=load_universe())


# The broker rate-limits quotes: about 45 in a burst exhausted it for several minutes
# (2026-10-19), and the guardrails need quotes and previews afterwards. So the daily
# check covers holdings, the benchmark and a slice of the rest that rotates by day.
DAILY_SLICE = 8
QUOTE_PAUSE_S = 1.0


def daily_check_set(all_isins: list[str], day: date, held: list[str], benchmark: str | None) -> list[str]:
    first = [i for i in [benchmark, *held] if i and i in all_isins]
    rest = [i for i in all_isins if i not in first]
    if not rest:
        return first
    start = (day.toordinal() * DAILY_SLICE) % len(rest)
    rotated = rest[start:] + rest[:start]
    return list(dict.fromkeys(first + rotated[:DAILY_SLICE]))


def _default_check_set(closes: pd.DataFrame) -> list[str]:
    from finance import clock, mandate, portfolio
    day = clock.today()
    state = portfolio.latest_state(day, dry_run=os.environ.get("FINANCE_DRY_RUN") == "1")
    held = [p.isin for p in state.positions] if state else []
    return daily_check_set(list(closes.columns), day, held, mandate.load().benchmark_isin)


def check_live(isins: list[str] | None = None, *, all_instruments: bool = False, pause_s: float = QUOTE_PAUSE_S) -> list[dict]:
    """Compare the last cached close with the broker's live mid quote. A gap above 3%
    usually means a bad ticker mapping or a stale cache, and the journal must say so."""
    import time
    closes = closes_by_isin()
    u = load_universe().set_index("isin")
    if not isins:
        isins = list(closes.columns) if all_instruments else _default_check_set(closes)
    out = []
    for n, isin in enumerate(isins):
        if n and pause_s:
            time.sleep(pause_s)
        try:
            q = sc.quote(isin)
        except sc.ScError as exc:
            out.append({"isin": isin, "error": exc.to_dict()["message"]})
            if exc.is_auth or exc.error_code == "rate_limited":
                break
            continue
        mid = sc.num(q.get("quote_mid_price"))
        last = float(closes[isin].dropna().iloc[-1]) if isin in closes and not closes[isin].dropna().empty else None
        gap = (mid / last - 1.0) if (mid and last) else None
        out.append({"isin": isin, "name": u.loc[isin, "name"] if isin in u.index else isin,
                    "sc_mid": mid, "sc_currency": q.get("quote_currency"), "last_close": last,
                    "gap_pct": round(gap * 100, 2) if gap is not None else None,
                    "flag": bool(gap is not None and abs(gap) > 0.03)})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="download recent closes into the cache")
    ap.add_argument("--full", action="store_true", help="rebuild the cache from scratch")
    ap.add_argument("--check-live", action="store_true", help="compare cached closes with sc quotes")
    ap.add_argument("--isin", action="append", help="limit --check-live to these ISINs")
    ap.add_argument("--all", action="store_true", help="--check-live every instrument, not the daily set")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result: dict = {}
    if args.refresh or args.full:
        closes, report = refresh(full=args.full)
        result["refresh"] = report
        if not args.json:
            print(f"closes: {len(closes)} rows x {closes.shape[1]} tickers, as of {report['as_of']}")
            if report["missing"]:
                print("MISSING (no data at all):", ", ".join(report["missing"]))
            for s in report["stale"]:
                print(f"STALE: {s['ticker']} last close {s['last']}")
            if report["filled_from_hourly"]:
                print("FILLED FROM HOURLY BARS (daily series lagging):", ", ".join(report["filled_from_hourly"]))
            if report["missing_days"]:
                print("MISSING TRADING DAYS (no close anywhere yet):", ", ".join(report["missing_days"]))
    if args.check_live:
        rows = check_live(args.isin, all_instruments=args.all)
        result["check_live"] = rows
        if not args.json:
            for r in rows:
                if "error" in r:
                    print(f"{r['isin']}: ERROR {r['error']}")
                else:
                    flag = "  <-- CHECK" if r["flag"] else ""
                    print(f"{r['isin']} {r['name'][:40]:40s} close={r['last_close']} sc_mid={r['sc_mid']} gap={r['gap_pct']}%{flag}")
    if not (args.refresh or args.full or args.check_live):
        md = market_data()
        result["cache"] = {"as_of": md.as_of.isoformat(), "instruments": int(md.closes.shape[1]), "rows": int(len(md.closes))}
        if not args.json:
            print(json.dumps(result["cache"]))
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
