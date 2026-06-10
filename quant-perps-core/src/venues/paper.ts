import {
  type AccountState,
  type Order,
  type OrderResult,
  type Position,
  type Quote,
  type Side,
  opposite,
  posNotional,
  posUnrealizedPnl,
  sideSign,
} from "../types.js";
import type { PriceSource } from "./base.js";

// Deterministic perp simulation backing any venue in paper mode. Nets
// positions, averages entry on adds, realises PnL on reductions/flips, applies
// taker slippage, and reports a margin-style account. Mirrors the Python broker.
export class PaperBroker {
  cash: number;
  realizedPnl = 0;
  private positions = new Map<string, Position>();

  constructor(
    public readonly venue: string,
    private readonly priceSource: PriceSource,
    startingEquity = 100_000,
    private readonly slippageBps = 2,
  ) {
    this.cash = startingEquity;
  }

  getQuote(symbol: string): Quote | null {
    return this.priceSource.quote(symbol);
  }

  private fillPrice(order: Order, quote: Quote): number {
    // Marketable orders take liquidity at the book (ask for buys, bid for
    // sells); a limit is then capped so the fill is never worse than authorised.
    const base = order.side === "long" ? quote.ask : quote.bid;
    const slip = base * (this.slippageBps / 1e4);
    let fill = order.side === "long" ? base + slip : base - slip;
    if (order.orderType === "limit" && order.limitPrice !== undefined) {
      fill =
        order.side === "long"
          ? Math.min(fill, order.limitPrice)
          : Math.max(fill, order.limitPrice);
    }
    return fill;
  }

  placeOrder(order: Order): OrderResult {
    const quote = this.getQuote(order.symbol);
    if (!quote)
      return this.rejected(order, `no price for ${order.symbol}`);

    const existing = this.positions.get(order.symbol);
    if (order.reduceOnly && !existing)
      return this.rejected(order, "reduce_only order with no open position");

    // Non-marketable limits rest (PENDING) instead of filling at an impossible
    // price. We don't model a resting book, so they simply apply no fill.
    if (order.orderType === "limit" && order.limitPrice !== undefined) {
      const marketable =
        order.side === "long"
          ? order.limitPrice >= quote.ask
          : order.limitPrice <= quote.bid;
      if (!marketable)
        return {
          order,
          status: "pending",
          venue: this.venue,
          filledSize: 0,
          avgPrice: 0,
          venueOrderId: `paper-${order.clientId}`,
          reason: "limit not marketable; resting",
        };
    }

    const fillPx = this.fillPrice(order, quote);
    let fillSize = order.size;
    if (order.reduceOnly && existing)
      fillSize = Math.min(order.size, existing.size);

    this.applyFill(order.symbol, order.side, fillSize, fillPx);

    return {
      order,
      status: "filled",
      venue: this.venue,
      filledSize: fillSize,
      avgPrice: fillPx,
      venueOrderId: `paper-${order.clientId}`,
      reason: "paper fill",
    };
  }

  private applyFill(
    symbol: string,
    side: Side,
    size: number,
    price: number,
  ): void {
    const existing = this.positions.get(symbol);
    const orderSigned = sideSign(side) * size;

    if (!existing || existing.size === 0) {
      this.positions.set(symbol, {
        symbol,
        venue: this.venue,
        side,
        size,
        entryPrice: price,
        markPrice: price,
        leverage: 1,
      });
      return;
    }

    const currentSigned = sideSign(existing.side) * existing.size;
    const newSigned = currentSigned + orderSigned;
    const sameDirection = currentSigned > 0 === orderSigned > 0;

    if (sameDirection) {
      const total = existing.size + size;
      existing.entryPrice =
        (existing.entryPrice * existing.size + price * size) / total;
      existing.size = total;
      existing.markPrice = price;
      return;
    }

    // opposite direction: realise PnL on the closed portion
    const closed = Math.min(existing.size, size);
    const pnl = sideSign(existing.side) * (price - existing.entryPrice) * closed;
    this.realizedPnl += pnl;
    this.cash += pnl;

    if (Math.abs(newSigned) < 1e-12) {
      this.positions.delete(symbol);
    } else if (newSigned > 0 === currentSigned > 0) {
      existing.size = Math.abs(newSigned);
      existing.markPrice = price;
    } else {
      existing.side = side;
      existing.size = Math.abs(newSigned);
      existing.entryPrice = price;
      existing.markPrice = price;
    }
  }

  closePosition(symbol: string): OrderResult {
    const pos = this.positions.get(symbol);
    if (!pos || pos.size === 0) {
      const dummy: Order = {
        symbol,
        side: "long",
        size: 1,
        orderType: "market",
        reduceOnly: true,
        tif: "gtc",
        clientId: "close",
      };
      return this.rejected(dummy, "no open position");
    }
    const order: Order = {
      symbol,
      side: opposite(pos.side),
      size: pos.size,
      orderType: "market",
      reduceOnly: true,
      tif: "gtc",
      clientId: `close-${symbol}`,
      note: "paper close",
    };
    return this.placeOrder(order);
  }

  private markPositions(): void {
    for (const pos of this.positions.values()) {
      const q = this.getQuote(pos.symbol);
      if (q) pos.markPrice = (q.bid + q.ask) / 2;
    }
  }

  getPositions(): Position[] {
    this.markPositions();
    return [...this.positions.values()].filter((p) => p.size > 0);
  }

  getAccount(): AccountState {
    const positions = this.getPositions();
    const unrealized = positions.reduce((s, p) => s + posUnrealizedPnl(p), 0);
    const used = positions.reduce((s, p) => s + posNotional(p), 0);
    const equity = this.cash + unrealized;
    return {
      venue: this.venue,
      equity,
      freeCollateral: Math.max(0, equity - used),
      positions,
    };
  }

  private rejected(order: Order, reason: string): OrderResult {
    return {
      order,
      status: "rejected",
      venue: this.venue,
      filledSize: 0,
      avgPrice: 0,
      reason,
    };
  }
}
