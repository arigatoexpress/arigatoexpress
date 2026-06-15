import { describe, expect, it } from "vitest";
import {
  RobinhoodAdapter,
  type RobinhoodClient,
  type RobinhoodSnapshot,
  mapRobinhoodAccount,
} from "../src/venues/robinhood.js";
import { makeOrder } from "../src/types.js";

function fakeClient(snap: RobinhoodSnapshot): RobinhoodClient {
  return { fetchSnapshot: async () => snap };
}

function snapshot(): RobinhoodSnapshot {
  return {
    fetchedAt: Date.now(),
    account: mapRobinhoodAccount({
      portfolioValueUsd: 5_000,
      buyingPowerUsd: 1_200,
      positions: [
        { symbol: "AAPL", quantity: 10, averageBuyPriceUsd: 180, markPriceUsd: 200 },
        { symbol: "DOGE", quantity: 0, averageBuyPriceUsd: 0.1, markPriceUsd: 0.2 },
      ],
    }),
    quotes: {
      AAPL: { symbol: "AAPL", venue: "robinhood", bid: 199.9, ask: 200.1 },
    },
  };
}

describe("RobinhoodAdapter (read-only)", () => {
  it("maps account payload, dropping zero-qty holdings", () => {
    const acct = snapshot().account;
    expect(acct.equity).toBe(5_000);
    expect(acct.freeCollateral).toBe(1_200);
    expect(acct.positions).toHaveLength(1);
    expect(acct.positions[0]!.symbol).toBe("AAPL");
    expect(acct.positions[0]!.side).toBe("long");
  });

  it("reports a fail-closed zero-equity account before refresh", () => {
    const a = new RobinhoodAdapter(fakeClient(snapshot()), ["AAPL"]);
    expect(a.getAccount().equity).toBe(0);
    expect(a.getPositions()).toHaveLength(0);
    expect(a.getQuote("AAPL")).toBeNull();
    expect(a.lastFetchedAt).toBeNull();
  });

  it("serves the snapshot after refresh", async () => {
    const a = new RobinhoodAdapter(fakeClient(snapshot()), ["AAPL"]);
    await a.refresh();
    expect(a.getAccount().equity).toBe(5_000);
    expect(a.getQuote("AAPL")!.ask).toBe(200.1);
    expect(a.lastFetchedAt).not.toBeNull();
  });

  it("is flagged live and non-perps", () => {
    const a = new RobinhoodAdapter(fakeClient(snapshot()), ["AAPL"]);
    expect(a.isLive).toBe(true);
    expect(a.supportsPerps).toBe(false);
  });

  it("REJECTS all order placement (read-only)", async () => {
    const a = new RobinhoodAdapter(fakeClient(snapshot()), ["AAPL"]);
    await a.refresh();
    const buy = a.placeOrder(makeOrder({ symbol: "AAPL", side: "long", size: 1 }));
    expect(buy.status).toBe("rejected");
    expect(buy.reason).toContain("read-only");
    expect(a.closePosition("AAPL").status).toBe("rejected");
  });
});
