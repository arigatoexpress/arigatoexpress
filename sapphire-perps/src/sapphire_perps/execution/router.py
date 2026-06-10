"""Order router: the one path from an Order to a venue.

Every order flows: resolve venue -> price -> risk kernel -> (live? approval) ->
adapter. Rejections short-circuit and are returned as ``OrderResult`` objects
(never exceptions for normal flow) so callers always get a structured outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config import AppConfig
from ..risk.kernel import RiskDecision, RiskKernel
from ..types import Order, OrderResult, OrderStatus, OrderType, Side
from ..venues.base import VenueAdapter
from .approval import ApprovalGate, AutoDenyGate

log = logging.getLogger("sapphire_perps.router")


@dataclass
class OrderRouter:
    venues: dict[str, VenueAdapter]
    risk: RiskKernel
    config: AppConfig
    approval: ApprovalGate = field(default_factory=AutoDenyGate)
    # Optional manual PnL offset added on top of the derived session PnL
    # (e.g. to seed a known prior loss). Normally left at 0.0.
    daily_pnl: float = 0.0
    # Per-venue equity captured on first sight, used as the session baseline so
    # the daily-loss circuit breaker reflects real drawdown without an external
    # caller having to feed it in.
    _equity_baseline: dict[str, float] = field(default_factory=dict)

    def _resolve_venue(self, order: Order) -> str:
        return order.venue or self.config.default_venue

    def _session_pnl(self, account) -> float:
        baseline = self._equity_baseline.setdefault(account.venue, account.equity)
        return (account.equity - baseline) + self.daily_pnl

    def _reject(self, order: Order, reason: str, venue: str = "") -> OrderResult:
        log.warning("order rejected: %s (%s)", reason, order.symbol)
        return OrderResult(
            order=order, status=OrderStatus.REJECTED, venue=venue, reason=reason
        )

    def submit(self, order: Order) -> OrderResult:
        venue_name = self._resolve_venue(order)
        order.venue = venue_name

        adapter = self.venues.get(venue_name)
        if adapter is None:
            return self._reject(order, f"venue {venue_name!r} not available", venue_name)

        if not adapter.supports_perps and not order.reduce_only:
            return self._reject(
                order, f"venue {venue_name!r} does not support perps", venue_name
            )

        quote = adapter.get_quote(order.symbol)
        if quote is None:
            return self._reject(order, f"no quote for {order.symbol}", venue_name)
        # Evaluate risk at the WORST-CASE executable price, not the mid, so a
        # fill can't sneak above a hard limit that was only checked at the mid.
        # - Market buy lifts the ask, market sell hits the bid.
        # - A marketable limit fills at the touch (ask/bid), which can be worse
        #   than the limit price; a resting limit fills no worse than its limit.
        #   Highest-notional fill: buy -> min(ask, limit); sell -> max(bid, limit).
        if order.order_type is OrderType.LIMIT and order.limit_price is not None:
            price = (
                min(quote.ask, order.limit_price)
                if order.side is Side.LONG
                else max(quote.bid, order.limit_price)
            )
        else:
            price = quote.ask if order.side is Side.LONG else quote.bid

        account = adapter.get_account()
        daily_pnl = self._session_pnl(account)

        decision = self.risk.evaluate(order, price, account, daily_pnl)
        if not decision.approved:
            return self._reject(
                order, "risk: " + "; ".join(decision.reasons), venue_name
            )

        # --- live double-gate -------------------------------------------
        if adapter.is_live:
            if not self.config.is_live:
                return self._reject(
                    order,
                    "live adapter but system not cleared for live "
                    "(need exec_mode=live AND allow_live=true)",
                    venue_name,
                )
            if not self.approval.request(order, decision, price):
                return self._reject(order, "human approval denied", venue_name)

        result = adapter.place_order(order)
        log.info(
            "order %s on %s: %s @ %s",
            result.status.value, venue_name, order.symbol,
            f"{result.avg_price:,.2f}" if result.ok else "-",
        )
        return result

    def close(self, symbol: str, venue: str | None = None) -> OrderResult:
        venue_name = venue or self.config.default_venue
        adapter = self.venues.get(venue_name)
        # A placeholder order so rejections carry a structured result.
        placeholder = Order(symbol=symbol, side=Side.LONG, size=1.0, reduce_only=True)
        if adapter is None:
            return self._reject(placeholder, f"venue {venue_name!r} not available", venue_name)

        # Closing reduces risk, but live orders face the same two-switch gate
        # and human approval as opening orders.
        if adapter.is_live:
            if not self.config.is_live:
                return self._reject(
                    placeholder,
                    "live adapter but system not cleared for live "
                    "(need exec_mode=live AND allow_live=true)",
                    venue_name,
                )
            quote = adapter.get_quote(symbol)
            price = quote.mid if quote else 0.0
            if not self.approval.request(placeholder, RiskDecision.approve("close"), price):
                return self._reject(placeholder, "human approval denied", venue_name)
        return adapter.close_position(symbol)
