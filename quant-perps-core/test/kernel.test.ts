import { describe, expect, it } from "vitest";
import { defaultRiskLimits, type RiskLimits } from "../src/config.js";
import { RiskKernel } from "../src/risk/kernel.js";
import {
  type AccountState,
  type Position,
  makeOrder,
} from "../src/types.js";

function limits(): RiskLimits {
  return {
    ...defaultRiskLimits(),
    maxOrderNotionalUsd: 10_000,
    minOrderNotionalUsd: 100,
    maxPositionNotionalUsd: 20_000,
    maxTotalNotionalUsd: 50_000,
    maxLeverage: 10,
    maxOpenPositions: 2,
    dailyLossLimitUsd: 1_000,
    allowedSymbols: ["BTC", "ETH"],
    blacklistSymbols: [],
  };
}
const kernel = () => new RiskKernel(limits());
const emptyAccount = (): AccountState => ({
  venue: "paper",
  equity: 100_000,
  freeCollateral: 100_000,
  positions: [],
});
const pos = (
  symbol: string,
  side: "long" | "short",
  size: number,
  px: number,
): Position => ({
  symbol,
  venue: "paper",
  side,
  size,
  entryPrice: px,
  markPrice: px,
  leverage: 1,
});

describe("RiskKernel", () => {
  it("approves within limits", () => {
    const d = kernel().evaluate(
      makeOrder({ symbol: "BTC", side: "long", size: 0.05 }),
      100_000,
      emptyAccount(),
    );
    expect(d.approved).toBe(true);
  });

  it("rejects missing price and account (fail closed)", () => {
    expect(
      kernel().evaluate(
        makeOrder({ symbol: "BTC", side: "long", size: 0.05 }),
        0,
        emptyAccount(),
      ).approved,
    ).toBe(false);
    expect(
      kernel().evaluate(
        makeOrder({ symbol: "BTC", side: "long", size: 0.05 }),
        100_000,
        null,
      ).approved,
    ).toBe(false);
  });

  it("rejects disallowed and blacklisted symbols", () => {
    const d = kernel().evaluate(
      makeOrder({ symbol: "DOGE", side: "long", size: 1 }),
      1,
      emptyAccount(),
    );
    expect(d.approved).toBe(false);
  });

  it("enforces order notional caps", () => {
    expect(
      kernel().evaluate(
        makeOrder({ symbol: "BTC", side: "long", size: 1 }),
        100_000,
        emptyAccount(),
      ).approved,
    ).toBe(false); // $100k > $10k
    expect(
      kernel().evaluate(
        makeOrder({ symbol: "BTC", side: "long", size: 0.0001 }),
        100_000,
        emptyAccount(),
      ).approved,
    ).toBe(false); // $10 < $100 min
  });

  it("enforces effective leverage without an explicit field", () => {
    const acct: AccountState = {
      venue: "paper",
      equity: 100,
      freeCollateral: 100,
      positions: [],
    };
    const d = kernel().evaluate(
      makeOrder({ symbol: "BTC", side: "long", size: 0.05 }),
      100_000,
      acct,
    );
    expect(d.approved).toBe(false);
    expect(d.reasons.some((r) => r.includes("effective leverage"))).toBe(true);
  });

  it("validates reduce-only orders actually reduce", () => {
    const noPos = kernel().evaluate(
      makeOrder({ symbol: "BTC", side: "short", size: 0.05, reduceOnly: true }),
      100_000,
      emptyAccount(),
    );
    expect(noPos.approved).toBe(false);

    const acct: AccountState = {
      venue: "paper",
      equity: 100_000,
      freeCollateral: 100_000,
      positions: [pos("BTC", "long", 0.05, 100_000)],
    };
    const sameSide = kernel().evaluate(
      makeOrder({ symbol: "BTC", side: "long", size: 0.05, reduceOnly: true }),
      100_000,
      acct,
    );
    expect(sameSide.approved).toBe(false);
  });

  it("daily-loss breaker blocks new but allows reduce-only", () => {
    const acct: AccountState = {
      venue: "paper",
      equity: 100_000,
      freeCollateral: 100_000,
      positions: [pos("BTC", "long", 0.05, 100_000)],
    };
    expect(
      kernel().evaluate(
        makeOrder({ symbol: "ETH", side: "long", size: 1 }),
        3_000,
        acct,
        -1_500,
      ).approved,
    ).toBe(false);
    expect(
      kernel().evaluate(
        makeOrder({ symbol: "BTC", side: "short", size: 0.05, reduceOnly: true }),
        100_000,
        acct,
        -1_500,
      ).approved,
    ).toBe(true);
  });
});
