"""Sapphire Perps — automated perpetual-futures trading system.

Paper-first, fail-closed, human-approval-gated execution across multiple
perp venues (Hyperliquid, Lighter, Robinhood).

Design tenets (inherited from the wider Sapphire stack):
  * Paper before production — every venue has a simulation backing.
  * Fail closed — missing data, missing config, or missing approval => no trade.
  * Human stays in charge — live orders pass through an approval gate.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .types import (
    AccountState,
    ExecMode,
    Instrument,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
    TimeInForce,
)

__all__ = [
    "__version__",
    "AccountState",
    "ExecMode",
    "Instrument",
    "Order",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "Position",
    "Quote",
    "Side",
    "TimeInForce",
]
