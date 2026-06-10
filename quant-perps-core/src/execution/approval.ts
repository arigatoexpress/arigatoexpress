import type { RiskDecision } from "../risk/kernel.js";
import type { Order } from "../types.js";

// Human approval gates for live orders. The default DENIES, so a system with no
// explicit approver can never place a live order (fail-closed in code form).
export interface ApprovalGate {
  request(order: Order, decision: RiskDecision, price: number): boolean;
}

export class AutoDenyGate implements ApprovalGate {
  request(): boolean {
    return false;
  }
}

// ONLY for tests / explicit unattended runs the operator has opted into.
export class AutoApproveGate implements ApprovalGate {
  request(): boolean {
    return true;
  }
}

// Delegates to a caller-supplied predicate (e.g. a UI confirmation in the
// quant-perps terminal). The default gate stays AutoDeny.
export class CallbackApprovalGate implements ApprovalGate {
  constructor(
    private fn: (order: Order, decision: RiskDecision, price: number) => boolean,
  ) {}
  request(order: Order, decision: RiskDecision, price: number): boolean {
    return this.fn(order, decision, price);
  }
}
