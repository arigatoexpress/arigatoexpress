import type {
  AccountState,
  Order,
  OrderResult,
  Position,
  Quote,
} from "../types.js";

// Supplies quotes to a paper broker (or anything needing marks).
export interface PriceSource {
  quote(symbol: string): Quote | null;
}

function bookFromMid(
  venue: string,
  symbol: string,
  mid: number,
  spreadBps: number,
): Quote | null {
  if (!(mid > 0)) return null;
  const half = (mid * (spreadBps / 1e4)) / 2;
  return { symbol, venue, bid: mid - half, ask: mid + half };
}

export class StaticPriceSource implements PriceSource {
  private prices: Map<string, number>;
  constructor(
    private venue: string,
    prices: Record<string, number>,
    private spreadBps = 1,
  ) {
    this.prices = new Map(Object.entries(prices));
  }
  setPrice(symbol: string, price: number): void {
    this.prices.set(symbol, price);
  }
  quote(symbol: string): Quote | null {
    const mid = this.prices.get(symbol);
    if (mid === undefined) return null;
    return bookFromMid(this.venue, symbol, mid, this.spreadBps);
  }
}

export class CallablePriceSource implements PriceSource {
  constructor(
    private venue: string,
    private fn: (symbol: string) => number | null,
    private spreadBps = 1,
  ) {}
  quote(symbol: string): Quote | null {
    let mid: number | null;
    try {
      mid = this.fn(symbol);
    } catch {
      return null;
    }
    if (mid === null) return null;
    return bookFromMid(this.venue, symbol, mid, this.spreadBps);
  }
}

// Uniform interface every venue implements. `isLive` distinguishes a real-money
// adapter from a paper one; the router uses it to gate the approval flow.
export interface VenueAdapter {
  readonly name: string;
  readonly supportsPerps: boolean;
  readonly isLive: boolean;
  getQuote(symbol: string): Quote | null;
  getAccount(): AccountState;
  getPositions(): Position[];
  placeOrder(order: Order): OrderResult;
  closePosition(symbol: string): OrderResult;
}

export function describeVenue(v: VenueAdapter): string {
  return `${v.name} [${v.isLive ? "LIVE" : "paper"}, ${v.supportsPerps ? "perps" : "NO-perps"}]`;
}
