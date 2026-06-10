import { beforeEach, describe, expect, it } from "vitest";
import { makeOrder, positionFor } from "../src/types.js";
import { StaticPriceSource } from "../src/venues/base.js";
import { PaperBroker } from "../src/venues/paper.js";

let broker: PaperBroker;
beforeEach(() => {
  const src = new StaticPriceSource("paper", { BTC: 100_000, ETH: 3_000 }, 0);
  broker = new PaperBroker("paper", src, 1_000_000, 0);
});

describe("PaperBroker", () => {
  it("opens a long and tracks the position", () => {
    const r = broker.placeOrder(makeOrder({ symbol: "BTC", side: "long", size: 0.5 }));
    expect(r.status).toBe("filled");
    const p = positionFor(broker.getAccount(), "BTC")!;
    expect(p.side).toBe("long");
    expect(p.size).toBe(0.5);
  });

  it("blends entry when averaging up", () => {
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "long", size: 1 }));
    (broker as unknown as { priceSource: StaticPriceSource }).priceSource.setPrice(
      "BTC",
      120_000,
    );
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "long", size: 1 }));
    const p = positionFor(broker.getAccount(), "BTC")!;
    expect(p.size).toBe(2);
    expect(p.entryPrice).toBeCloseTo(110_000, 6);
  });

  it("realises PnL on close", () => {
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "long", size: 1 }));
    src().setPrice("BTC", 110_000);
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "short", size: 1 }));
    expect(broker.realizedPnl).toBeCloseTo(10_000, 6);
    expect(positionFor(broker.getAccount(), "BTC")).toBeUndefined();
  });

  it("flips long to short", () => {
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "long", size: 1 }));
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "short", size: 3 }));
    const p = positionFor(broker.getAccount(), "BTC")!;
    expect(p.side).toBe("short");
    expect(p.size).toBeCloseTo(2, 6);
  });

  it("caps reduce-only at the position size", () => {
    broker.placeOrder(makeOrder({ symbol: "BTC", side: "long", size: 1 }));
    const r = broker.placeOrder(
      makeOrder({ symbol: "BTC", side: "short", size: 5, reduceOnly: true }),
    );
    expect(r.filledSize).toBeCloseTo(1, 6);
    expect(positionFor(broker.getAccount(), "BTC")).toBeUndefined();
  });

  it("rests a non-marketable limit and fills a marketable one at the book", () => {
    const rest = broker.placeOrder(
      makeOrder({ symbol: "BTC", side: "long", size: 1, orderType: "limit", limitPrice: 99_000 }),
    );
    expect(rest.status).toBe("pending");
    expect(positionFor(broker.getAccount(), "BTC")).toBeUndefined();

    const fill = broker.placeOrder(
      makeOrder({ symbol: "BTC", side: "long", size: 1, orderType: "limit", limitPrice: 105_000 }),
    );
    expect(fill.status).toBe("filled");
    expect(fill.avgPrice).toBe(100_000); // book, not the 105k cap
  });
});

function src(): StaticPriceSource {
  return (broker as unknown as { priceSource: StaticPriceSource }).priceSource;
}
