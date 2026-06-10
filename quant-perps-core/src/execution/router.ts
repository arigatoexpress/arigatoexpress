import type { AppConfig } from "../config.js";
import { isLive } from "../config.js";
import type { RiskKernel } from "../risk/kernel.js";
import {
  type AccountState,
  type Order,
  type OrderResult,
  makeOrder,
} from "../types.js";
import type { VenueAdapter } from "../venues/base.js";
import { type ApprovalGate, AutoDenyGate } from "./approval.js";

// The one path from an Order to a venue: resolve venue -> executable price ->
// risk kernel -> (live? approval) -> adapter. Rejections are returned as
// structured OrderResults, never thrown.
export class OrderRouter {
  private equityBaseline = new Map<string, number>();

  constructor(
    public readonly venues: Map<string, VenueAdapter>,
    private readonly risk: RiskKernel,
    private readonly config: AppConfig,
    private readonly approval: ApprovalGate = new AutoDenyGate(),
    // Optional manual PnL offset added on top of derived session PnL.
    public dailyPnl = 0,
  ) {}

  private resolveVenue(order: Order): string {
    return order.venue ?? this.config.defaultVenue;
  }

  private sessionPnl(account: AccountState): number {
    let baseline = this.equityBaseline.get(account.venue);
    if (baseline === undefined) {
      baseline = account.equity;
      this.equityBaseline.set(account.venue, baseline);
    }
    return account.equity - baseline + this.dailyPnl;
  }

  private reject(order: Order, reason: string, venue = ""): OrderResult {
    return {
      order,
      status: "rejected",
      venue,
      filledSize: 0,
      avgPrice: 0,
      reason,
    };
  }

  submit(order: Order): OrderResult {
    const venueName = this.resolveVenue(order);
    order.venue = venueName;
    const adapter = this.venues.get(venueName);
    if (!adapter)
      return this.reject(order, `venue '${venueName}' not available`, venueName);

    if (!adapter.supportsPerps && !order.reduceOnly)
      return this.reject(
        order,
        `venue '${venueName}' does not support perps`,
        venueName,
      );

    const quote = adapter.getQuote(order.symbol);
    if (!quote)
      return this.reject(order, `no quote for ${order.symbol}`, venueName);

    // Worst-case executable price (a fill can't sneak above a hard limit only
    // checked at the mid). Buy -> min(ask, limit); sell -> max(bid, limit).
    let price: number;
    if (order.orderType === "limit" && order.limitPrice !== undefined) {
      price =
        order.side === "long"
          ? Math.min(quote.ask, order.limitPrice)
          : Math.max(quote.bid, order.limitPrice);
    } else {
      price = order.side === "long" ? quote.ask : quote.bid;
    }

    const account = adapter.getAccount();
    const decision = this.risk.evaluate(
      order,
      price,
      account,
      this.sessionPnl(account),
    );
    if (!decision.approved)
      return this.reject(
        order,
        "risk: " + decision.reasons.join("; "),
        venueName,
      );

    if (adapter.isLive) {
      if (!isLive(this.config))
        return this.reject(
          order,
          "live adapter but system not cleared for live " +
            "(need execMode=live AND allowLive=true)",
          venueName,
        );
      if (!this.approval.request(order, decision, price))
        return this.reject(order, "human approval denied", venueName);
    }

    return adapter.placeOrder(order);
  }

  close(symbol: string, venue?: string): OrderResult {
    const venueName = venue ?? this.config.defaultVenue;
    const adapter = this.venues.get(venueName);
    const placeholder = makeOrder({
      symbol,
      side: "long",
      size: 1,
      reduceOnly: true,
    });
    if (!adapter)
      return this.reject(
        placeholder,
        `venue '${venueName}' not available`,
        venueName,
      );

    if (adapter.isLive) {
      if (!isLive(this.config))
        return this.reject(
          placeholder,
          "live adapter but system not cleared for live " +
            "(need execMode=live AND allowLive=true)",
          venueName,
        );
      const quote = adapter.getQuote(symbol);
      const price = quote ? (quote.bid + quote.ask) / 2 : 0;
      if (
        !this.approval.request(
          placeholder,
          { approved: true, reasons: ["close"] },
          price,
        )
      )
        return this.reject(placeholder, "human approval denied", venueName);
    }
    return adapter.closePosition(symbol);
  }
}
