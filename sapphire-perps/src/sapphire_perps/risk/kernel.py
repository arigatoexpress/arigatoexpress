"""The risk kernel: the single chokepoint every order passes through before
it can reach a venue.

Philosophy: **fail closed**. The kernel approves an order only when it can
prove the order is within every configured limit. Missing price data, missing
account state, or an unrecognised symbol all result in rejection — never a
silent pass-through.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import RiskLimits
from ..types import AccountState, Order


@dataclass
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)

    @classmethod
    def approve(cls, note: str = "within limits") -> RiskDecision:
        return cls(approved=True, reasons=[note])

    @classmethod
    def reject(cls, reasons: list[str]) -> RiskDecision:
        return cls(approved=False, reasons=reasons)

    def __bool__(self) -> bool:  # allows `if decision:`
        return self.approved


def _resulting_signed_size(order: Order, account: AccountState) -> float:
    existing = account.position_for(order.symbol)
    current = existing.signed_size if existing else 0.0
    return current + order.signed_size


class RiskKernel:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def evaluate(
        self,
        order: Order,
        price: float,
        account: AccountState,
        daily_pnl: float = 0.0,
    ) -> RiskDecision:
        reasons: list[str] = []
        lim = self.limits

        # --- fail-closed preconditions ----------------------------------
        if account is None:
            return RiskDecision.reject(["no account state available"])
        if price is None or price <= 0:
            return RiskDecision.reject([f"no valid mark price for {order.symbol}"])
        if order.size <= 0:
            return RiskDecision.reject(["order size must be positive"])

        # --- circuit breaker: daily loss limit --------------------------
        # Checked first so a tripped breaker blocks even reduce-only churn that
        # isn't explicitly closing risk. Reduce-only orders are still allowed
        # through so positions can be flattened.
        if daily_pnl <= -abs(lim.daily_loss_limit_usd) and not order.reduce_only:
            reasons.append(
                f"daily loss limit hit (pnl={daily_pnl:.2f} "
                f"<= -{lim.daily_loss_limit_usd:.2f}); only reduce-only allowed"
            )

        # --- symbol allowlist -------------------------------------------
        if order.symbol not in lim.allowed_symbols:
            reasons.append(f"symbol {order.symbol!r} not in allowlist")

        # --- leverage ----------------------------------------------------
        if order.leverage is not None and order.leverage > lim.max_leverage:
            reasons.append(
                f"leverage {order.leverage} exceeds max {lim.max_leverage}"
            )

        order_notional = order.size * price

        # --- reduce-only validity ---------------------------------------
        # A reduce_only order is exempt from the increase-only limits below, so
        # we must PROVE it actually reduces. It reduces only when there is an
        # existing position on the OPPOSITE side. With no position, or one on
        # the same side, "reduce_only" would instead open/increase exposure —
        # reject it rather than let it bypass the caps.
        if order.reduce_only:
            existing = account.position_for(order.symbol)
            if existing is None or existing.size == 0:
                reasons.append("reduce_only order but no open position to reduce")
            elif existing.side is order.side:
                reasons.append(
                    f"reduce_only order on same side as existing {order.symbol} "
                    "position would increase exposure, not reduce it"
                )

        # Increase-only checks are skipped for (validated) reduce-only orders,
        # which can only shrink risk.
        if not order.reduce_only:
            if order_notional < lim.min_order_notional_usd:
                reasons.append(
                    f"order notional ${order_notional:,.2f} below min "
                    f"${lim.min_order_notional_usd:,.2f}"
                )
            if order_notional > lim.max_order_notional_usd:
                reasons.append(
                    f"order notional ${order_notional:,.2f} exceeds max "
                    f"${lim.max_order_notional_usd:,.2f}"
                )

            resulting_notional = abs(_resulting_signed_size(order, account)) * price
            if resulting_notional > lim.max_position_notional_usd:
                reasons.append(
                    f"resulting {order.symbol} position ${resulting_notional:,.2f} "
                    f"exceeds max ${lim.max_position_notional_usd:,.2f}"
                )

            projected_total = self._projected_total_notional(order, account, price)
            if projected_total > lim.max_total_notional_usd:
                reasons.append(
                    f"projected total notional ${projected_total:,.2f} exceeds max "
                    f"${lim.max_total_notional_usd:,.2f}"
                )

            if self._opens_new_position(order, account):
                if account.open_position_count >= lim.max_open_positions:
                    reasons.append(
                        f"already at max open positions ({lim.max_open_positions})"
                    )

        if reasons:
            return RiskDecision.reject(reasons)
        return RiskDecision.approve()

    # ------------------------------------------------------------------
    def _opens_new_position(self, order: Order, account: AccountState) -> bool:
        existing = account.position_for(order.symbol)
        return existing is None or existing.size == 0

    def _projected_total_notional(
        self, order: Order, account: AccountState, price: float
    ) -> float:
        total = 0.0
        touched = False
        for pos in account.positions:
            if pos.symbol == order.symbol:
                touched = True
                signed = pos.signed_size + order.signed_size
                total += abs(signed) * price
            else:
                total += pos.notional
        if not touched:
            total += abs(order.signed_size) * price
        return total
