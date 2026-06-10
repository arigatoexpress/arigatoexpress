import { type AccountState, type Quote, type Side, sideSign } from "../types.js";

// A desired target exposure for one symbol. `targetSide` null means flat.
export interface Intent {
  symbol: string;
  targetSide: Side | null;
  targetNotionalUsd: number;
  reason: string;
}

export const signedTarget = (i: Intent): number =>
  i.targetSide === null ? 0 : sideSign(i.targetSide) * i.targetNotionalUsd;

// A signal consumes market data + account and emits target intents. Signals
// never place orders; the engine turns intent deltas into risk-checked orders.
export interface Signal {
  readonly name: string;
  evaluate(quotes: Map<string, Quote>, account: AccountState): Intent[];
}
