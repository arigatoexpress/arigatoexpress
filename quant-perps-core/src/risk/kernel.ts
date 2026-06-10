import type { RiskLimits } from "../config.js";
import {
  type AccountState,
  type Order,
  orderSignedSize,
  positionFor,
  posNotional,
  openPositionCount,
} from "../types.js";

// The single chokepoint every order passes through. Fail closed: an order is
// approved only when it can be proven within every configured limit.
export interface RiskDecision {
  approved: boolean;
  reasons: string[];
}
const approve = (note = "within limits"): RiskDecision => ({
  approved: true,
  reasons: [note],
});
const reject = (reasons: string[]): RiskDecision => ({
  approved: false,
  reasons,
});

function resultingSignedSize(order: Order, account: AccountState): number {
  const existing = positionFor(account, order.symbol);
  const current = existing ? sideSigned(existing) : 0;
  return current + orderSignedSize(order);
}
function sideSigned(p: { side: "long" | "short"; size: number }): number {
  return (p.side === "long" ? 1 : -1) * p.size;
}

export class RiskKernel {
  constructor(private readonly limits: RiskLimits) {}

  evaluate(
    order: Order,
    price: number,
    account: AccountState | null,
    dailyPnl = 0,
  ): RiskDecision {
    const reasons: string[] = [];
    const lim = this.limits;

    // fail-closed preconditions
    if (!account) return reject(["no account state available"]);
    if (!(price > 0)) return reject([`no valid mark price for ${order.symbol}`]);
    if (!(order.size > 0)) return reject(["order size must be positive"]);

    // circuit breaker: daily loss limit (reduce-only still allowed to flatten)
    if (dailyPnl <= -Math.abs(lim.dailyLossLimitUsd) && !order.reduceOnly) {
      reasons.push(
        `daily loss limit hit (pnl=${dailyPnl.toFixed(2)} <= ` +
          `-${lim.dailyLossLimitUsd.toFixed(2)}); only reduce-only allowed`,
      );
    }

    // symbol allow/deny lists
    if (lim.blacklistSymbols.includes(order.symbol))
      reasons.push(`symbol ${order.symbol} is blacklisted`);
    if (lim.allowedSymbols.length > 0 && !lim.allowedSymbols.includes(order.symbol))
      reasons.push(`symbol ${order.symbol} not in allowlist`);

    // per-order leverage field (opt-in; account leverage enforced below)
    if (order.leverage !== undefined && order.leverage > lim.maxLeverage)
      reasons.push(`leverage ${order.leverage} exceeds max ${lim.maxLeverage}`);

    const orderNotional = order.size * price;

    // reduce-only validity: must have an opposite-side position to reduce
    if (order.reduceOnly) {
      const existing = positionFor(account, order.symbol);
      if (!existing || existing.size === 0)
        reasons.push("reduce_only order but no open position to reduce");
      else if (existing.side === order.side)
        reasons.push(
          `reduce_only order on same side as existing ${order.symbol} ` +
            "position would increase exposure, not reduce it",
        );
    }

    if (!order.reduceOnly) {
      if (orderNotional < lim.minOrderNotionalUsd)
        reasons.push(
          `order notional ${fmt(orderNotional)} below min ${fmt(lim.minOrderNotionalUsd)}`,
        );
      if (orderNotional > lim.maxOrderNotionalUsd)
        reasons.push(
          `order notional ${fmt(orderNotional)} exceeds max ${fmt(lim.maxOrderNotionalUsd)}`,
        );

      const resultingNotional =
        Math.abs(resultingSignedSize(order, account)) * price;
      if (resultingNotional > lim.maxPositionNotionalUsd)
        reasons.push(
          `resulting ${order.symbol} position ${fmt(resultingNotional)} ` +
            `exceeds max ${fmt(lim.maxPositionNotionalUsd)}`,
        );

      const projectedTotal = this.projectedTotalNotional(order, account, price);
      if (projectedTotal > lim.maxTotalNotionalUsd)
        reasons.push(
          `projected total notional ${fmt(projectedTotal)} exceeds max ${fmt(lim.maxTotalNotionalUsd)}`,
        );

      // account leverage cap from post-trade notional / equity
      if (account.equity <= 0)
        reasons.push(
          `non-positive account equity (${fmt(account.equity)}); cannot size order`,
        );
      else {
        const effLev = projectedTotal / account.equity;
        if (effLev > lim.maxLeverage)
          reasons.push(
            `effective leverage ${effLev.toFixed(2)}x (${fmt(projectedTotal)} / ` +
              `${fmt(account.equity)} equity) exceeds max ${lim.maxLeverage}x`,
          );
      }

      if (this.opensNewPosition(order, account)) {
        if (openPositionCount(account) >= lim.maxOpenPositions)
          reasons.push(`already at max open positions (${lim.maxOpenPositions})`);
      }
    }

    return reasons.length ? reject(reasons) : approve();
  }

  private opensNewPosition(order: Order, account: AccountState): boolean {
    const existing = positionFor(account, order.symbol);
    return !existing || existing.size === 0;
  }

  private projectedTotalNotional(
    order: Order,
    account: AccountState,
    price: number,
  ): number {
    let total = 0;
    let touched = false;
    for (const pos of account.positions) {
      if (pos.symbol === order.symbol) {
        touched = true;
        const signed = sideSigned(pos) + orderSignedSize(order);
        total += Math.abs(signed) * price;
      } else {
        total += posNotional(pos);
      }
    }
    if (!touched) total += Math.abs(orderSignedSize(order)) * price;
    return total;
  }
}

const fmt = (n: number): string =>
  `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
