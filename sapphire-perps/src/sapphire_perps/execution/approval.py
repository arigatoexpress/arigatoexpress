"""Human approval gates for live orders.

The default gate denies — a system with no explicit approver configured can
never place a live order. This is the fail-closed posture in code form.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..risk.kernel import RiskDecision
from ..types import Order


class ApprovalGate(ABC):
    @abstractmethod
    def request(self, order: Order, decision: RiskDecision, price: float) -> bool:
        """Return True to allow the live order, False to block it."""


class AutoDenyGate(ApprovalGate):
    """Default gate: blocks every live order. Safe by construction."""

    def request(self, order: Order, decision: RiskDecision, price: float) -> bool:
        return False


class AutoApproveGate(ApprovalGate):
    """Approves automatically. ONLY for tests / explicit unattended runs the
    operator has opted into. Never the default."""

    def request(self, order: Order, decision: RiskDecision, price: float) -> bool:
        return True


class CLIApprovalGate(ApprovalGate):
    """Interactive y/N confirmation in the terminal."""

    def request(self, order: Order, decision: RiskDecision, price: float) -> bool:  # pragma: no cover - interactive
        notional = order.size * price
        print("\n=== LIVE ORDER APPROVAL REQUIRED ===")
        print(f"  {order.side.value.upper()} {order.size} {order.symbol} "
              f"@ ~{price:,.2f}  (~${notional:,.2f} notional)")
        print(f"  venue={order.venue}  type={order.order_type.value}  "
              f"reduce_only={order.reduce_only}")
        print(f"  risk: {', '.join(decision.reasons)}")
        try:
            answer = input("  Approve? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("  -> no input; denying.")
            return False
        approved = answer in {"y", "yes"}
        print(f"  -> {'APPROVED' if approved else 'DENIED'}")
        return approved
