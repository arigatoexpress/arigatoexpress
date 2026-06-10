"""A simple, transparent reference signal: dual-SMA momentum.

Keeps a rolling window of mid prices per symbol. When the fast SMA crosses
above the slow SMA it targets a long; below, a short; otherwise flat. Position
size is a fixed fraction of account equity, capped per symbol.

This exists to exercise the full loop with understandable behaviour — it is a
starting point, not alpha. Swap in your own ``Signal`` implementation.
"""

from __future__ import annotations

from collections import defaultdict, deque

from ..types import AccountState, Quote, Side
from .base import Intent


class MomentumSignal:
    name = "dual_sma_momentum"

    def __init__(
        self,
        fast: int = 8,
        slow: int = 21,
        equity_fraction: float = 0.10,
        max_notional_usd: float = 5_000.0,
    ):
        if fast >= slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast = fast
        self.slow = slow
        self.equity_fraction = equity_fraction
        self.max_notional_usd = max_notional_usd
        self._history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=slow)
        )

    def _sma(self, values: deque[float], n: int) -> float | None:
        if len(values) < n:
            return None
        window = list(values)[-n:]
        return sum(window) / n

    def evaluate(
        self, quotes: dict[str, Quote], account: AccountState
    ) -> list[Intent]:
        intents: list[Intent] = []
        budget = min(
            self.max_notional_usd, account.equity * self.equity_fraction
        )
        for symbol, quote in quotes.items():
            hist = self._history[symbol]
            hist.append(quote.mid)
            fast = self._sma(hist, self.fast)
            slow = self._sma(hist, self.slow)
            if fast is None or slow is None:
                # Not enough data yet — emit no opinion (hold current state).
                continue
            if fast > slow:
                intents.append(
                    Intent(symbol, Side.LONG, budget, f"fast {fast:.2f} > slow {slow:.2f}")
                )
            elif fast < slow:
                intents.append(
                    Intent(symbol, Side.SHORT, budget, f"fast {fast:.2f} < slow {slow:.2f}")
                )
            else:
                intents.append(Intent(symbol, None, 0.0, "fast == slow -> flat"))
        return intents
