"""Plain data types shared by the strategy, the backtest, the snapshot and guardrails."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any, Literal

import pandas as pd

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop"]


@dataclass(frozen=True)
class Position:
    isin: str
    name: str
    quantity: float
    price: float            # last mid price in EUR
    value_eur: float
    fifo_price: float | None = None
    security_type: str | None = None

    @property
    def unrealised_pct(self) -> float | None:
        if not self.fifo_price:
            return None
        return self.price / self.fifo_price - 1.0


@dataclass(frozen=True)
class PortfolioState:
    as_of: date
    nav: float
    cash: float
    buying_power: float
    positions: tuple[Position, ...] = ()
    pending_buy_orders_eur: float = 0.0
    dry_run: bool = False

    def position(self, isin: str) -> Position | None:
        for p in self.positions:
            if p.isin == isin:
                return p
        return None

    def weight(self, isin: str) -> float:
        p = self.position(isin)
        return (p.value_eur / self.nav) if (p and self.nav) else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["as_of"] = self.as_of.isoformat()
        d["positions"] = [asdict(p) for p in self.positions]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PortfolioState":
        return cls(
            as_of=date.fromisoformat(d["as_of"]),
            nav=float(d["nav"]),
            cash=float(d["cash"]),
            buying_power=float(d.get("buying_power", d["cash"])),
            positions=tuple(Position(**{k: p.get(k) for k in Position.__dataclass_fields__}) for p in d.get("positions", [])),
            pending_buy_orders_eur=float(d.get("pending_buy_orders_eur", 0.0)),
            dry_run=bool(d.get("dry_run", False)),
        )


@dataclass(frozen=True)
class MarketData:
    """Daily closes in EUR, index = date, columns = ISIN. `as_of` is the last row
    the strategy is allowed to see (no look-ahead)."""
    closes: pd.DataFrame
    as_of: date
    universe: pd.DataFrame   # columns: isin, ticker, name, type, prime (bool)

    def history(self) -> pd.DataFrame:
        return self.closes.loc[: pd.Timestamp(self.as_of)]


@dataclass(frozen=True)
class ProposedOrder:
    isin: str
    side: Side
    order_type: OrderType = "market"
    eur_amount: float | None = None
    quantity: float | None = None
    limit_price: float | None = None
    rationale: str = ""
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.side not in ("buy", "sell"):
            raise ValueError(f"bad side {self.side!r}")
        if self.side == "buy" and (self.eur_amount is None) == (self.quantity is None):
            raise ValueError("buy needs exactly one of eur_amount or quantity")
        if self.side == "sell" and not self.quantity:
            raise ValueError("sell needs a positive quantity")
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit order needs limit_price")
