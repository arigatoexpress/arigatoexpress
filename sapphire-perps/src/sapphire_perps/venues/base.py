"""Venue adapter interface and price-source abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from ..types import AccountState, Order, OrderResult, Position, Quote


class PriceSource(ABC):
    """Supplies quotes to a paper broker (or anything else that needs marks)."""

    @abstractmethod
    def quote(self, symbol: str) -> Quote | None:
        ...


class StaticPriceSource(PriceSource):
    """A fixed price book — used for fully offline paper trading and tests."""

    def __init__(self, venue: str, prices: dict[str, float], spread_bps: float = 1.0):
        self.venue = venue
        self._prices = dict(prices)
        self.spread_bps = spread_bps

    def set_price(self, symbol: str, price: float) -> None:
        self._prices[symbol] = price

    def quote(self, symbol: str) -> Quote | None:
        mid = self._prices.get(symbol)
        if mid is None or mid <= 0:
            return None
        half = mid * (self.spread_bps / 1e4) / 2.0
        return Quote(symbol=symbol, venue=self.venue, bid=mid - half, ask=mid + half)


class CallablePriceSource(PriceSource):
    """Wraps a plain function ``symbol -> mid price`` into a PriceSource."""

    def __init__(self, venue: str, fn: Callable[[str], float | None], spread_bps: float = 1.0):
        self.venue = venue
        self._fn = fn
        self.spread_bps = spread_bps

    def quote(self, symbol: str) -> Quote | None:
        try:
            mid = self._fn(symbol)
        except Exception:
            return None
        if mid is None or mid <= 0:
            return None
        half = mid * (self.spread_bps / 1e4) / 2.0
        return Quote(symbol=symbol, venue=self.venue, bid=mid - half, ask=mid + half)


class VenueAdapter(ABC):
    """Uniform interface every venue must implement.

    ``is_live`` distinguishes a real-money adapter from a paper one. The router
    uses it to decide whether the approval gate is required.
    """

    name: str = "base"
    supports_perps: bool = True
    is_live: bool = False

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote | None:
        ...

    @abstractmethod
    def get_account(self) -> AccountState:
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        ...

    @abstractmethod
    def place_order(self, order: Order) -> OrderResult:
        ...

    @abstractmethod
    def close_position(self, symbol: str) -> OrderResult:
        ...

    def describe(self) -> str:
        mode = "LIVE" if self.is_live else "paper"
        perps = "perps" if self.supports_perps else "NO-perps"
        return f"{self.name} [{mode}, {perps}]"
