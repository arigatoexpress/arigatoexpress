import { describe, expect, it } from "vitest";
import { type AppConfig, defaultConfig } from "../src/config.js";
import { AutoApproveGate, AutoDenyGate } from "../src/execution/approval.js";
import { OrderRouter } from "../src/execution/router.js";
import { RiskKernel } from "../src/risk/kernel.js";
import {
  type AccountState,
  type Order,
  type OrderResult,
  type Position,
  type Quote,
  makeOrder,
} from "../src/types.js";
import { StaticPriceSource, type VenueAdapter } from "../src/venues/base.js";
import { PaperBroker } from "../src/venues/paper.js";

class FakeVenue implements VenueAdapter {
  readonly name = "fake";
  readonly supportsPerps = true;
  readonly isLive: boolean;
  broker: PaperBroker;
  constructor(isLive = false, spreadBps = 0) {
    this.isLive = isLive;
    this.broker = new PaperBroker(
      "fake",
      new StaticPriceSource("fake", { BTC: 100_000 }, spreadBps),
      1_000_000,
      0,
    );
  }
  getQuote(s: string): Quote | null {
    return this.broker.getQuote(s);
  }
  getAccount(): AccountState {
    return this.broker.getAccount();
  }
  getPositions(): Position[] {
    return this.broker.getPositions();
  }
  placeOrder(o: Order): OrderResult {
    return this.broker.placeOrder(o);
  }
  closePosition(s: string): OrderResult {
    return this.broker.closePosition(s);
  }
}

function config(): AppConfig {
  const c = defaultConfig();
  c.defaultVenue = "fake";
  c.risk = {
    ...c.risk,
    allowedSymbols: ["BTC", "ETH"],
    maxOrderNotionalUsd: 1_000_000,
    maxPositionNotionalUsd: 5_000_000,
    maxTotalNotionalUsd: 10_000_000,
  };
  return c;
}
function router(c: AppConfig, venue: VenueAdapter, approval = new AutoDenyGate()) {
  return new OrderRouter(
    new Map([[venue.name, venue]]),
    new RiskKernel(c.risk),
    c,
    approval,
  );
}

describe("OrderRouter", () => {
  it("fills a paper order", () => {
    const r = router(config(), new FakeVenue());
    expect(r.submit(makeOrder({ symbol: "BTC", side: "long", size: 0.1 })).status).toBe(
      "filled",
    );
  });

  it("short-circuits on risk rejection", () => {
    const c = config();
    c.risk.allowedSymbols = ["ETH"];
    const res = router(c, new FakeVenue()).submit(
      makeOrder({ symbol: "BTC", side: "long", size: 0.1 }),
    );
    expect(res.status).toBe("rejected");
    expect(res.reason).toContain("risk:");
  });

  it("blocks live when system not cleared", () => {
    const c = config();
    c.defaultVenue = "fake";
    const live = new FakeVenue(true);
    const res = router(c, live, new AutoApproveGate()).submit(
      makeOrder({ symbol: "BTC", side: "long", size: 0.1 }),
    );
    expect(res.status).toBe("rejected");
    expect(res.reason).toContain("not cleared for live");
  });

  it("allows live only when cleared and approved", () => {
    const c = config();
    c.execMode = "live";
    c.allowLive = true;
    const live = new FakeVenue(true);
    expect(
      router(c, live, new AutoDenyGate()).submit(
        makeOrder({ symbol: "BTC", side: "long", size: 0.1 }),
      ).status,
    ).toBe("rejected");
    expect(
      router(c, live, new AutoApproveGate()).submit(
        makeOrder({ symbol: "BTC", side: "long", size: 0.1 }),
      ).status,
    ).toBe("filled");
  });

  it("blocks live close when not cleared", () => {
    const c = config();
    const res = router(c, new FakeVenue(true), new AutoApproveGate()).close("BTC");
    expect(res.status).toBe("rejected");
    expect(res.reason).toContain("not cleared for live");
  });

  it("daily-loss breaker trips from derived PnL but allows reduce-only", () => {
    const c = config();
    c.risk.dailyLossLimitUsd = 5_000;
    const venue = new FakeVenue();
    const r = router(c, venue);
    expect(r.submit(makeOrder({ symbol: "BTC", side: "long", size: 1 })).status).toBe(
      "filled",
    );
    venue.broker.getQuote("BTC"); // ensure baseline captured before the drop
    (venue.broker as unknown as { priceSource: StaticPriceSource }).priceSource.setPrice(
      "BTC",
      90_000,
    );
    const blocked = r.submit(makeOrder({ symbol: "BTC", side: "long", size: 0.1 }));
    expect(blocked.status).toBe("rejected");
    expect(blocked.reason).toContain("daily loss");
    expect(
      r.submit(makeOrder({ symbol: "BTC", side: "short", size: 0.5, reduceOnly: true }))
        .status,
    ).toBe("filled");
  });

  it("risk-checks market orders at the executable price", () => {
    const c = config();
    c.risk.maxOrderNotionalUsd = 10_000;
    const venue = new FakeVenue(false, 2_000); // ask = 110k
    const res = router(c, venue).submit(
      makeOrder({ symbol: "BTC", side: "long", size: 0.0999 }),
    );
    expect(res.status).toBe("rejected"); // $10,989 at ask > $10k
  });
});
