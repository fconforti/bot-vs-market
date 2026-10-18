"""Load mandate.toml fresh every time it is asked for. Never cache."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import paths


@dataclass(frozen=True)
class Limits:
    max_order_pct_of_nav: float
    max_orders_per_day: int
    max_position_pct_of_nav: float
    min_order_eur: float
    cash_reserve_eur: float
    allow_market_orders: bool
    allow_limit_orders: bool
    allow_stop_orders: bool
    reject_on_price_warning: bool
    reject_on_appropriateness: bool
    preview_amount_tolerance: float

    def allowed_order_types(self) -> set[str]:
        out = set()
        if self.allow_market_orders:
            out.add("market")
        if self.allow_limit_orders:
            out.add("limit")
        if self.allow_stop_orders:
            out.add("stop")
        return out


@dataclass(frozen=True)
class Mandate:
    limits: Limits
    venue: str
    require_selected_venue_match: bool
    trading_days: tuple[str, ...]
    session_time: str
    timezone: str
    holidays: frozenset[date]
    benchmark_isin: str
    benchmark_ticker: str
    benchmark_name: str
    benchmark_initial_eur: float
    order_fee_eur: float
    crypto_etp_spread_surcharge: float
    append_only_dirs: tuple[str, ...] = field(default_factory=tuple)
    append_only_exceptions: tuple[str, ...] = field(default_factory=tuple)
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    def is_trading_day(self, d: date) -> bool:
        weekday = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")[d.weekday()]
        return weekday in self.trading_days and d not in self.holidays


def _load_holidays(path: Path) -> frozenset[date]:
    if not path.exists():
        return frozenset()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    out: set[date] = set()
    for _year, days in raw.get("xetra", {}).items():
        for d in days:
            out.add(date.fromisoformat(str(d)))
    return frozenset(out)


def load(path: Path | None = None) -> Mandate:
    path = path or paths.MANDATE_TOML
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    lim = raw["limits"]
    limits = Limits(
        max_order_pct_of_nav=float(lim["max_order_pct_of_nav"]),
        max_orders_per_day=int(lim["max_orders_per_day"]),
        max_position_pct_of_nav=float(lim["max_position_pct_of_nav"]),
        min_order_eur=float(lim["min_order_eur"]),
        cash_reserve_eur=float(lim.get("cash_reserve_eur", 0.0)),
        allow_market_orders=bool(lim.get("allow_market_orders", True)),
        allow_limit_orders=bool(lim.get("allow_limit_orders", False)),
        allow_stop_orders=bool(lim.get("allow_stop_orders", False)),
        reject_on_price_warning=bool(lim.get("reject_on_price_warning", True)),
        reject_on_appropriateness=bool(lim.get("reject_on_appropriateness", True)),
        preview_amount_tolerance=float(lim.get("preview_amount_tolerance", 0.01)),
    )
    sched = raw.get("schedule", {})
    holidays_file = path.parent / sched.get("holidays_file", "data/holidays.toml")
    bench = raw["benchmark"]
    fees = raw.get("fees", {})
    honesty = raw.get("honesty", {})
    venue = raw.get("venue", {})
    return Mandate(
        limits=limits,
        venue=str(venue.get("code", "")).strip(),
        require_selected_venue_match=bool(venue.get("require_selected_venue_match", True)),
        trading_days=tuple(sched.get("trading_days", ["Mon", "Tue", "Wed", "Thu", "Fri"])),
        session_time=str(sched.get("session_time", "18:15")),
        timezone=str(sched.get("timezone", "Europe/Rome")),
        holidays=_load_holidays(holidays_file),
        benchmark_isin=bench["isin"],
        benchmark_ticker=bench.get("yfinance_ticker", ""),
        benchmark_name=bench.get("name", bench["isin"]),
        benchmark_initial_eur=float(bench.get("initial_eur", 1000.0)),
        order_fee_eur=float(fees.get("order_fee_eur", 0.99)),
        crypto_etp_spread_surcharge=float(fees.get("crypto_etp_spread_surcharge", 0.0)),
        append_only_dirs=tuple(honesty.get("append_only_dirs", [])),
        append_only_exceptions=tuple(honesty.get("append_only_exceptions", [])),
        raw=raw,
    )
