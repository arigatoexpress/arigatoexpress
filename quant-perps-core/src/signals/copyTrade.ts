import { type AccountState, type Quote, type Side } from "../types.js";
import type { Intent, Signal } from "./base.js";

// What the bot wants to mirror per symbol: the tracked wallet's direction and
// leverage (null side => the wallet is flat, so we should be flat too).
export interface CloneTarget {
  side: Side | null;
  leverage: number;
}

// Replaces quant-perps' inline `handleBotAutoOpen` sizing: turns a tracked
// wallet's positions into target intents, applying the leverage ceiling and
// per-trade size budget. The risk kernel still vets every resulting order, so
// the clone can never exceed the configured caps.
export class CopyTradeSignal implements Signal {
  readonly name = "copy_trade";

  constructor(
    private readonly targets: () => Map<string, CloneTarget>,
    private readonly collateralUsd: number,
    private readonly maxPositionSizePercent: number,
    private readonly maxLeverage: number,
  ) {}

  evaluate(quotes: Map<string, Quote>, _account: AccountState): Intent[] {
    const intents: Intent[] = [];
    for (const [symbol, target] of this.targets()) {
      if (!quotes.has(symbol)) continue;
      if (target.side === null) {
        intents.push({
          symbol,
          targetSide: null,
          targetNotionalUsd: 0,
          reason: "tracked wallet flat",
        });
        continue;
      }
      const safeLeverage = Math.min(target.leverage, this.maxLeverage);
      const notional =
        this.collateralUsd * (this.maxPositionSizePercent / 100) * safeLeverage;
      intents.push({
        symbol,
        targetSide: target.side,
        targetNotionalUsd: notional,
        reason: `clone ${target.side} @ ${safeLeverage}x`,
      });
    }
    return intents;
  }
}
