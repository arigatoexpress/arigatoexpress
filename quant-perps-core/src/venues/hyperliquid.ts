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

// Conservative offline marks for paper mode. A live TS Hyperliquid client wires
// in behind `isLive` later (see docs/LIVE_HARDENING.md in sapphire-perps).
const FALLBACK_PRICES: Record<string, number> = {
  BTC: 96_000,
  ETH: 3_400,
  SOL: 180,
  HYPE: 28,
  ARB: 0.9,
};

export class HyperliquidAdapter implements VenueAdapter {
  readonly name = "hyperliquid";
  readonly supportsPerps = true;
  readonly isLive: boolean;
  private broker: PaperBroker;

  constructor(config: AppConfig) {
    this.isLive = isLive(config);
    if (this.isLive) {
      // Live routing intentionally not wired in this port. Fail closed.
      throw new Error(
        "Hyperliquid live routing is not wired in quant-perps-core yet; " +
          "run in paper mode. See LIVE_HARDENING.md.",
      );
    }
    this.broker = new PaperBroker(
      this.name,
      new StaticPriceSource(this.name, FALLBACK_PRICES, 2),
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

  // Pure helpers carried from the Python live path, ready for the live client.
  static roundPx(px: number, maxDecimals = 6): number {
    if (px <= 0) return px;
    const sig = Number(px.toPrecision(5));
    const f = 10 ** maxDecimals;
    return Math.round(sig * f) / f;
  }
  static roundSize(size: number, szDecimals: number): number {
    const f = 10 ** szDecimals;
    return Math.floor(Math.abs(size) * f) / f;
  }
}
