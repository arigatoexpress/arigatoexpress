import type { AppConfig } from "./config.js";
import type { OrderRouter } from "./execution/router.js";
import { type Intent, type Signal, signedTarget } from "./signals/base.js";
import {
  type Order,
  type OrderResult,
  type Quote,
  type Side,
  makeOrder,
  positionFor,
  posSignedSize,
} from "./types.js";

// Don't churn on tiny deltas.
const MIN_REBALANCE_NOTIONAL_USD = 50;

// Wires signal -> intents -> orders -> router. One step() is a full decision
// cycle: pull quotes, ask the signal for targets, diff each against the current
// position, and route the delta order (risk + approval enforced in the router).
export class Engine {
  constructor(
    private readonly config: AppConfig,
    private readonly router: OrderRouter,
    private readonly signal: Signal,
    private readonly symbols: string[],
    private readonly venue: string = config.defaultVenue,
  ) {}

  private collectQuotes(): Map<string, Quote> {
    const adapter = this.router.venues.get(this.venue)!;
    const quotes = new Map<string, Quote>();
    for (const symbol of this.symbols) {
      const q = adapter.getQuote(symbol);
      if (q) quotes.set(symbol, q);
    }
    return quotes;
  }

  // Translate a target exposure into one delta order, or null if no action.
  intentToOrder(intent: Intent, quote: Quote): Order | null {
    const adapter = this.router.venues.get(this.venue)!;
    const account = adapter.getAccount();
    const pos = positionFor(account, intent.symbol);
    const mid = (quote.bid + quote.ask) / 2;
    const currentSignedNotional = pos ? posSignedSize(pos) * mid : 0;
    const targetSignedNotional = signedTarget(intent);
    const deltaNotional = targetSignedNotional - currentSignedNotional;

    if (Math.abs(deltaNotional) < MIN_REBALANCE_NOTIONAL_USD) return null;

    const side: Side = deltaNotional > 0 ? "long" : "short";
    // Size at the executable price (matches the router's risk price) so a
    // cap-hugging target isn't tripped by the spread.
    const execPrice = side === "long" ? quote.ask : quote.bid;
    const size = Math.abs(deltaNotional) / execPrice;

    // reduce_only ONLY when purely shrinking the same side (or closing). A
    // target that crosses zero must flip via a normal close+open, not a
    // mis-marked reduce_only that would drop the new-side exposure.
    const crossing =
      currentSignedNotional !== 0 &&
      targetSignedNotional !== 0 &&
      currentSignedNotional > 0 !== targetSignedNotional > 0;
    const reduceOnly =
      pos !== undefined &&
      !crossing &&
      Math.abs(targetSignedNotional) < Math.abs(currentSignedNotional);

    return makeOrder({
      symbol: intent.symbol,
      side,
      size,
      orderType: "market",
      reduceOnly,
      venue: this.venue,
      note: intent.reason,
    });
  }

  step(): OrderResult[] {
    const quotes = this.collectQuotes();
    if (quotes.size === 0) return [];
    const adapter = this.router.venues.get(this.venue)!;
    const account = adapter.getAccount();
    const intents = this.signal.evaluate(quotes, account);

    const results: OrderResult[] = [];
    for (const intent of intents) {
      const quote = quotes.get(intent.symbol);
      if (!quote) continue;
      const order = this.intentToOrder(intent, quote);
      if (!order) continue;
      results.push(this.router.submit(order));
    }
    return results;
  }
}
