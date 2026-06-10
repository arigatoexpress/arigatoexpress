"""In-memory paper broker.

A deterministic perp simulation used as the backing for any venue in paper
mode. It nets positions, applies configurable slippage, realises PnL on
reductions/flips, and reports a margin-style account snapshot.

It is intentionally simple (no funding, no liquidation engine) — enough to
exercise the full signal -> risk -> execution loop without touching real money.
"""

from __future__ import annotations

from ..types import (
    AccountState,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
)
from .base import PriceSource


class PaperBroker:
    def __init__(
        self,
        venue: str,
        price_source: PriceSource,
        starting_equity: float = 100_000.0,
        slippage_bps: float = 2.0,
    ):
        self.venue = venue
        self.price_source = price_source
        self.cash = float(starting_equity)
        self.realized_pnl = 0.0
        self.slippage_bps = slippage_bps
        self._positions: dict[str, Position] = {}

    # -- market data ---------------------------------------------------
    def get_quote(self, symbol: str) -> Quote | None:
        return self.price_source.quote(symbol)

    def _fill_price(self, order: Order, quote: Quote) -> float:
        if order.order_type is OrderType.LIMIT and order.limit_price is not None:
            base = order.limit_price
        else:
            base = quote.ask if order.side is Side.LONG else quote.bid
        slip = base * (self.slippage_bps / 1e4)
        # Slippage always works against the taker.
        return base + slip if order.side is Side.LONG else base - slip

    # -- execution -----------------------------------------------------
    def place_order(self, order: Order) -> OrderResult:
        quote = self.get_quote(order.symbol)
        if quote is None:
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                venue=self.venue,
                reason=f"no price for {order.symbol}",
            )

        existing = self._positions.get(order.symbol)
        if order.reduce_only and existing is None:
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                venue=self.venue,
                reason="reduce_only order with no open position",
            )

        # A limit order only executes if it's marketable. A buy must cross the
        # ask, a sell must cross the bid; otherwise it rests (PENDING) rather
        # than filling at an impossible price. We don't model a resting book, so
        # a non-marketable limit simply stays pending and applies no fill.
        if order.order_type is OrderType.LIMIT and order.limit_price is not None:
            marketable = (
                order.limit_price >= quote.ask
                if order.side is Side.LONG
                else order.limit_price <= quote.bid
            )
            if not marketable:
                return OrderResult(
                    order=order,
                    status=OrderStatus.PENDING,
                    venue=self.venue,
                    venue_order_id=f"paper-{order.client_id}",
                    reason="limit not marketable; resting",
                )

        fill_px = self._fill_price(order, quote)
        fill_size = order.size
        if order.reduce_only and existing is not None:
            fill_size = min(order.size, existing.size)

        self._apply_fill(order.symbol, order.side, fill_size, fill_px)

        return OrderResult(
            order=order,
            status=OrderStatus.FILLED,
            venue=self.venue,
            filled_size=fill_size,
            avg_price=fill_px,
            venue_order_id=f"paper-{order.client_id}",
            reason="paper fill",
        )

    def _apply_fill(self, symbol: str, side: Side, size: float, price: float) -> None:
        existing = self._positions.get(symbol)
        order_signed = side.sign * size

        if existing is None or existing.size == 0:
            self._positions[symbol] = Position(
                symbol=symbol,
                venue=self.venue,
                side=side,
                size=size,
                entry_price=price,
                mark_price=price,
            )
            return

        current_signed = existing.signed_size
        new_signed = current_signed + order_signed

        same_direction = (current_signed > 0) == (order_signed > 0)
        if same_direction:
            # Average up/down — no realised PnL.
            total = existing.size + size
            existing.entry_price = (
                existing.entry_price * existing.size + price * size
            ) / total
            existing.size = total
            existing.mark_price = price
            return

        # Opposite direction: realise PnL on the closed portion.
        closed = min(existing.size, size)
        self.realized_pnl += existing.side.sign * (price - existing.entry_price) * closed
        self.cash += existing.side.sign * (price - existing.entry_price) * closed

        if abs(new_signed) < 1e-12:
            del self._positions[symbol]
        elif (new_signed > 0) == (current_signed > 0):
            # Reduced but same side.
            existing.size = abs(new_signed)
            existing.mark_price = price
        else:
            # Flipped: leftover opens a fresh position at the fill price.
            existing.side = side
            existing.size = abs(new_signed)
            existing.entry_price = price
            existing.mark_price = price

    def close_position(self, symbol: str) -> OrderResult:
        pos = self._positions.get(symbol)
        if pos is None or pos.size == 0:
            # Build a zero-size dummy order to satisfy the result contract.
            dummy = Order(symbol=symbol, side=Side.LONG, size=1.0, reduce_only=True)
            return OrderResult(
                order=dummy,
                status=OrderStatus.REJECTED,
                venue=self.venue,
                reason="no open position",
            )
        order = Order(
            symbol=symbol,
            side=pos.side.opposite,
            size=pos.size,
            reduce_only=True,
            note="paper close",
        )
        return self.place_order(order)

    # -- account -------------------------------------------------------
    def _mark_positions(self) -> None:
        for pos in self._positions.values():
            q = self.get_quote(pos.symbol)
            if q is not None:
                pos.mark_price = q.mid

    def get_positions(self) -> list[Position]:
        self._mark_positions()
        return [p for p in self._positions.values() if p.size > 0]

    def get_account(self) -> AccountState:
        self._mark_positions()
        positions = self.get_positions()
        unrealized = sum(p.unrealized_pnl for p in positions)
        used_margin = sum(p.notional for p in positions)
        equity = self.cash + unrealized
        free = max(0.0, equity - used_margin)
        return AccountState(
            venue=self.venue,
            equity=equity,
            free_collateral=free,
            positions=positions,
        )
