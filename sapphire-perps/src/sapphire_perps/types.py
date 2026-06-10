"""Core domain types shared across the engine.

Deliberately dependency-free (stdlib only) so the risk kernel, paper broker,
and tests never need a network or third-party package to run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


def _now() -> datetime:
    return datetime.now(UTC)


class Side(str, Enum):
    """Direction of a position or order."""

    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def opposite(self) -> Side:
        return Side.SHORT if self is Side.LONG else Side.LONG


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(str, Enum):
    GTC = "gtc"  # good-till-cancel
    IOC = "ioc"  # immediate-or-cancel
    ALO = "alo"  # add-liquidity-only / post-only


class ExecMode(str, Enum):
    """Whether orders are simulated or sent to a real venue."""

    PAPER = "paper"
    LIVE = "live"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Instrument:
    """A tradable perp contract on a specific venue."""

    symbol: str  # base asset, e.g. "BTC"
    venue: str
    quote_ccy: str = "USD"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.symbol}-PERP@{self.venue}"


@dataclass
class Quote:
    symbol: str
    venue: str
    bid: float
    ask: float
    ts: datetime = field(default_factory=_now)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        if self.mid <= 0:
            return 0.0
        return (self.ask - self.bid) / self.mid * 1e4


@dataclass
class Order:
    """An instruction to trade. ``size`` is always positive; ``side`` carries
    direction. ``reduce_only`` orders may only shrink an existing position."""

    symbol: str
    side: Side
    size: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    reduce_only: bool = False
    tif: TimeInForce = TimeInForce.GTC
    venue: str | None = None
    leverage: float | None = None
    client_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    note: str = ""

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("order size must be positive; use `side` for direction")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit orders require a limit_price")

    @property
    def signed_size(self) -> float:
        return self.side.sign * self.size


@dataclass
class OrderResult:
    order: Order
    status: OrderStatus
    venue: str = ""
    filled_size: float = 0.0
    avg_price: float = 0.0
    venue_order_id: str | None = None
    reason: str = ""
    ts: datetime = field(default_factory=_now)

    @property
    def ok(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)

    @property
    def notional(self) -> float:
        return self.filled_size * self.avg_price


@dataclass
class Position:
    symbol: str
    venue: str
    side: Side
    size: float  # > 0
    entry_price: float
    mark_price: float = 0.0
    leverage: float = 1.0

    @property
    def signed_size(self) -> float:
        return self.side.sign * self.size

    @property
    def mark(self) -> float:
        return self.mark_price or self.entry_price

    @property
    def notional(self) -> float:
        return self.size * self.mark

    @property
    def unrealized_pnl(self) -> float:
        return self.side.sign * (self.mark - self.entry_price) * self.size


@dataclass
class AccountState:
    venue: str
    equity: float  # cash + unrealized PnL, in quote ccy
    free_collateral: float
    positions: list[Position] = field(default_factory=list)
    ts: datetime = field(default_factory=_now)

    def position_for(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None

    @property
    def total_notional(self) -> float:
        return sum(p.notional for p in self.positions)

    @property
    def open_position_count(self) -> int:
        return sum(1 for p in self.positions if p.size > 0)
