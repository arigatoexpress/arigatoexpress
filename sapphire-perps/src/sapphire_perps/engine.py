"""The trading engine: wires signal -> intents -> orders -> router.

One ``step()`` is a full decision cycle:
  1. Pull quotes for the configured symbols from the active venue.
  2. Ask the signal for target intents.
  3. Diff each intent against the current position to produce an order.
  4. Submit each order through the router (risk + approval enforced there).

``run()`` repeats ``step()`` on an interval. Everything is paper by default.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .config import AppConfig
from .execution.router import OrderRouter
from .signals.base import Intent, Signal
from .types import Order, OrderResult, OrderType, Quote, Side

log = logging.getLogger("sapphire_perps.engine")

# Don't churn on tiny deltas — ignore rebalances below this notional.
MIN_REBALANCE_NOTIONAL_USD = 50.0


@dataclass
class Engine:
    config: AppConfig
    router: OrderRouter
    signal: Signal
    symbols: list[str] = field(default_factory=list)
    venue: str | None = None

    def __post_init__(self) -> None:
        self.venue = self.venue or self.config.default_venue
        if not self.symbols:
            self.symbols = list(self.config.risk.allowed_symbols)

    # ------------------------------------------------------------------
    def _collect_quotes(self) -> dict[str, Quote]:
        adapter = self.router.venues[self.venue]
        quotes: dict[str, Quote] = {}
        for symbol in self.symbols:
            q = adapter.get_quote(symbol)
            if q is not None:
                quotes[symbol] = q
        return quotes

    def _intent_to_order(self, intent: Intent, quote: Quote) -> Order | None:
        """Translate a target exposure into a delta order, or None if no action."""
        adapter = self.router.venues[self.venue]
        account = adapter.get_account()
        pos = account.position_for(intent.symbol)
        current_signed_notional = (
            pos.signed_size * quote.mid if pos else 0.0
        )
        target_signed_notional = intent.signed_target
        delta_notional = target_signed_notional - current_signed_notional

        if abs(delta_notional) < MIN_REBALANCE_NOTIONAL_USD:
            return None

        side = Side.LONG if delta_notional > 0 else Side.SHORT
        # Size off the executable price (ask for a buy, bid for a sell), the same
        # price the router uses for risk. Sizing off the mid would make a buy's
        # notional-at-the-ask exceed the target and trip the order cap for a
        # signal that targets exactly the max notional.
        exec_price = quote.ask if side is Side.LONG else quote.bid
        size = abs(delta_notional) / exec_price

        # Mark reduce_only ONLY when this order purely shrinks the existing
        # position without crossing zero (same-side smaller target, or a flat
        # target that closes it). When the target crosses to the opposite side
        # (e.g. +$10k long -> -$5k short), the order must flip — leaving it
        # non-reduce-only so the full close+open executes and we actually reach
        # the target, instead of a reduce_only order closing the long and
        # silently dropping the intended short.
        crossing = (
            current_signed_notional != 0.0
            and target_signed_notional != 0.0
            and (current_signed_notional > 0) != (target_signed_notional > 0)
        )
        reduce_only = (
            pos is not None
            and not crossing
            and abs(target_signed_notional) < abs(current_signed_notional)
        )
        return Order(
            symbol=intent.symbol,
            side=side,
            size=size,
            order_type=OrderType.MARKET,
            reduce_only=reduce_only,
            venue=self.venue,
            note=intent.reason,
        )

    # ------------------------------------------------------------------
    def step(self) -> list[OrderResult]:
        quotes = self._collect_quotes()
        if not quotes:
            log.warning("no quotes available for %s; skipping step", self.symbols)
            return []
        adapter = self.router.venues[self.venue]
        account = adapter.get_account()
        intents = self.signal.evaluate(quotes, account)

        results: list[OrderResult] = []
        for intent in intents:
            quote = quotes.get(intent.symbol)
            if quote is None:
                continue
            order = self._intent_to_order(intent, quote)
            if order is None:
                continue
            results.append(self.router.submit(order))
        return results

    def run(self, max_steps: int | None = None) -> None:
        log.info(
            "engine starting: venue=%s mode=%s symbols=%s",
            self.venue,
            "LIVE" if self.config.is_live else "paper",
            self.symbols,
        )
        step = 0
        try:
            while max_steps is None or step < max_steps:
                step += 1
                results = self.step()
                fills = [r for r in results if r.ok]
                log.info("step %d: %d orders, %d fills", step, len(results), len(fills))
                if max_steps is not None and step >= max_steps:
                    break
                time.sleep(self.config.poll_interval_s)
        except KeyboardInterrupt:  # pragma: no cover - interactive
            log.info("engine stopped by user")
