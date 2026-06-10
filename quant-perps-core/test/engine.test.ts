import { describe, expect, it } from "vitest";
import { type AppConfig, defaultConfig } from "../src/config.js";
import { AutoDenyGate } from "../src/execution/approval.js";
import { OrderRouter } from "../src/execution/router.js";
import { RiskKernel } from "../src/risk/kernel.js";
import type { Intent, Signal } from "../src/signals/base.js";
import { Engine } from "../src/engine.js";
import {
  type AccountState,
  type Order,
  type OrderResult,
  type Position,
  type Quote,
  type Side,
  isOk,
  positionFor,
} from "../src/types.js";
import { StaticPriceSource, type VenueAdapter } from "../src/venues/base.js";
import { PaperBroker } from "../src/venues/paper.js";

class PaperVenue implements VenueAdapter {
  readonly name = "paper";
  readonly supportsPerps = true;
  readonly isLive = false;
  src: StaticPriceSource;
  broker: PaperBroker;
  constructor(spreadBps = 0) {
    this.src = new StaticPriceSource("paper", { BTC: 100_000 }, spreadBps);
    this.broker = new PaperBroker("paper", this.src, 1_000_000, 0);
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

class TargetSignal implements Signal {
  readonly name = "target";
  constructor(
    public side: Side | null,
    public notional: number,
  ) {}
  evaluate(quotes: Map<string, Quote>): Intent[] {
    return [...quotes.keys()].map((symbol) => ({
      symbol,
      targetSide: this.side,
      targetNotionalUsd: this.notional,
      reason: "test",
    }));
  }
}

function build(signal: Signal, spreadBps = 0, maxOrder = 1_000_000) {
  const c: AppConfig = defaultConfig();
  c.defaultVenue = "paper";
  c.risk = {
    ...c.risk,
    allowedSymbols: ["BTC"],
    maxOrderNotionalUsd: maxOrder,
    maxPositionNotionalUsd: Math.max(maxOrder, 5_000_000),
    maxTotalNotionalUsd: Math.max(maxOrder, 10_000_000),
  };
  const venue = new PaperVenue(spreadBps);
  const router = new OrderRouter(
    new Map([["paper", venue]]),
    new RiskKernel(c.risk),
    c,
    new AutoDenyGate(),
  );
  return { engine: new Engine(c, router, signal, ["BTC"], "paper"), venue };
}

describe("Engine", () => {
  it("opens a position from an intent", () => {
    const { engine, venue } = build(new TargetSignal("long", 10_000));
    const results = engine.step();
    expect(results.some(isOk)).toBe(true);
    const p = positionFor(venue.getAccount(), "BTC")!;
    expect(p.side).toBe("long");
    expect(Math.abs(p.size - 0.1)).toBeLessThan(1e-6);
  });

  it("is idempotent at target", () => {
    const { engine, venue } = build(new TargetSignal("long", 10_000));
    engine.step();
    const first = positionFor(venue.getAccount(), "BTC")!.size;
    engine.step();
    const second = positionFor(venue.getAccount(), "BTC")!.size;
    expect(Math.abs(first - second)).toBeLessThan(1e-9);
  });

  it("flips across zero to reach a smaller opposite target", () => {
    const sig = new TargetSignal("long", 10_000);
    const { engine, venue } = build(sig);
    engine.step();
    expect(positionFor(venue.getAccount(), "BTC")!.side).toBe("long");
    sig.side = "short";
    sig.notional = 5_000;
    engine.step();
    const p = positionFor(venue.getAccount(), "BTC")!;
    expect(p.side).toBe("short");
    expect(Math.abs(p.size - 0.05)).toBeLessThan(1e-6);
  });

  it("sizes at the ask so a cap-hugging long opens despite spread", () => {
    const { engine, venue } = build(new TargetSignal("long", 5_000), 2, 5_000);
    const results = engine.step();
    expect(results.every(isOk)).toBe(true);
    expect(positionFor(venue.getAccount(), "BTC")!.side).toBe("long");
  });
});
