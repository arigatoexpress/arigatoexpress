import {
  type AccountState,
  type Order,
  type OrderResult,
  type Position,
  type Quote,
} from "../types.js";
import type { VenueAdapter } from "./base.js";

// ---------------------------------------------------------------------------
// Robinhood adapter — READ-ONLY by design.
//
// Robinhood is a real-money brokerage (equities / options / crypto), NOT a
// perps venue. This adapter exists so the system can READ the account
// (balances, positions, quotes) through the uniform VenueAdapter interface.
//
// Order placement is HARD-DISABLED here. `placeOrder`/`closePosition` always
// reject. Enabling real orders is a deliberate, separate step that must go
// through the OrderRouter's live gate + human approval AND a future
// purpose-built live client — never by flipping a flag in this file.
//
// Data is fetched ASYNCHRONOUSLY via a RobinhoodClient and cached into a
// snapshot, so the synchronous VenueAdapter surface (used by the router/engine)
// serves the most recent `refresh()`. Until the first successful refresh the
// adapter reports a zero-equity account, which the risk kernel treats as
// fail-closed (no order can size against zero equity).
// ---------------------------------------------------------------------------

export interface RobinhoodSnapshot {
  account: AccountState;
  quotes: Record<string, Quote>;
  fetchedAt: number;
}

// Transport-agnostic read client. A concrete impl can be backed by Robinhood's
// REST API (for the deployed server) or by the MCP tools (for interactive
// agent use); the adapter doesn't care which.
export interface RobinhoodClient {
  fetchSnapshot(symbols: string[]): Promise<RobinhoodSnapshot>;
}

const VENUE = "robinhood";

function emptyAccount(): AccountState {
  return { venue: VENUE, equity: 0, freeCollateral: 0, positions: [] };
}

export class RobinhoodAdapter implements VenueAdapter {
  readonly name = VENUE;
  readonly supportsPerps = false;
  // Real money is always involved, so we report this as a live venue: the
  // router will refuse to route orders unless the system is explicitly cleared
  // for live AND approval passes. (Orders are also blocked below regardless.)
  readonly isLive = true;

  private snapshot: RobinhoodSnapshot | null = null;

  constructor(
    private readonly client: RobinhoodClient,
    private readonly symbols: string[],
  ) {}

  // Pull a fresh read-only snapshot. Call before reading account/quotes.
  async refresh(): Promise<RobinhoodSnapshot> {
    this.snapshot = await this.client.fetchSnapshot(this.symbols);
    return this.snapshot;
  }

  get lastFetchedAt(): number | null {
    return this.snapshot?.fetchedAt ?? null;
  }

  getQuote(symbol: string): Quote | null {
    return this.snapshot?.quotes[symbol] ?? null;
  }

  getAccount(): AccountState {
    return this.snapshot?.account ?? emptyAccount();
  }

  getPositions(): Position[] {
    return this.snapshot?.account.positions ?? [];
  }

  // --- order placement: intentionally disabled -----------------------------
  placeOrder(order: Order): OrderResult {
    return {
      order,
      status: "rejected",
      venue: VENUE,
      filledSize: 0,
      avgPrice: 0,
      reason:
        "Robinhood adapter is read-only; live order placement is not enabled. " +
        "Enabling requires a dedicated live client + explicit approval.",
    };
  }

  closePosition(symbol: string): OrderResult {
    const placeholder: Order = {
      symbol,
      side: "long",
      size: 1,
      orderType: "market",
      reduceOnly: true,
      tif: "gtc",
      clientId: "rh-close",
    };
    return this.placeOrder(placeholder);
  }
}

// Maps a raw Robinhood-style account payload into our AccountState. Equities and
// RH crypto are long-only here (no native shorts), so every holding is `long`.
export function mapRobinhoodAccount(raw: {
  portfolioValueUsd: number;
  buyingPowerUsd: number;
  positions: {
    symbol: string;
    quantity: number;
    averageBuyPriceUsd: number;
    markPriceUsd: number;
  }[];
}): AccountState {
  const positions: Position[] = raw.positions
    .filter((p) => p.quantity > 0)
    .map((p) => ({
      symbol: p.symbol,
      venue: VENUE,
      side: "long" as const,
      size: p.quantity,
      entryPrice: p.averageBuyPriceUsd,
      markPrice: p.markPriceUsd,
      leverage: 1,
    }));
  return {
    venue: VENUE,
    equity: raw.portfolioValueUsd,
    freeCollateral: raw.buyingPowerUsd,
    positions,
  };
}
