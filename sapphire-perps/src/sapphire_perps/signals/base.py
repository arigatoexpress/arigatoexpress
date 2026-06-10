"""Signal interface.

A signal consumes market data (and optionally account state) and emits target
*intents* — desired exposures expressed in notional USD. The engine is
responsible for turning the delta between intent and current position into
concrete orders. Signals never place orders directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..types import AccountState, Quote, Side


@dataclass
class Intent:
    """A desired target exposure for one symbol.

    ``target_side`` of None means flat. ``target_notional_usd`` is the absolute
    notional to hold (>= 0); direction comes from ``target_side``.
    """

    symbol: str
    target_side: Side | None
    target_notional_usd: float = 0.0
    reason: str = ""

    @property
    def signed_target(self) -> float:
        if self.target_side is None:
            return 0.0
        return self.target_side.sign * self.target_notional_usd


@runtime_checkable
class Signal(Protocol):
    name: str

    def evaluate(
        self, quotes: dict[str, Quote], account: AccountState
    ) -> list[Intent]:
        ...
