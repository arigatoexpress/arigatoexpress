import type { AppConfig } from "../config.js";
import { isLive } from "../config.js";
import type {
  AccountState,
  Order,
  OrderResult,
  Position,
  Quote,
} from "../types.js";
import { StaticPriceSource, type VenueAdapter } from "./base.js";
import { PaperBroker } from "./paper.js";

const FALLBACK_PRICES: Record<string, number> = {
  BTC: 96_000,
  ETH: 3_400,
  SOL: 180,
};

// Lighter (zkLighter): paper-capable now; live SignerClient routing is a
// documented TODO. Fail closed on live.
export class LighterAdapter implements VenueAdapter {
  readonly name = "lighter";
  readonly supportsPerps = true;
  readonly isLive: boolean;
  private broker: PaperBroker;

  constructor(config: AppConfig) {
    this.isLive = isLive(config);
    if (this.isLive)
      throw new Error(
        "Lighter live trading is not wired yet; run in paper mode.",
      );
    this.broker = new PaperBroker(
      this.name,
      new StaticPriceSource(this.name, FALLBACK_PRICES, 3),
      config.paperStartingEquityUsd,
      config.paperSlippageBps,
    );
  }

  getQuote(symbol: string): Quote | null {
    return this.broker.getQuote(symbol);
  }
  getAccount(): AccountState {
    return this.broker.getAccount();
  }
  getPositions(): Position[] {
    return this.broker.getPositions();
  }
  placeOrder(order: Order): OrderResult {
    return this.broker.placeOrder(order);
  }
  closePosition(symbol: string): OrderResult {
    return this.broker.closePosition(symbol);
  }
}
