import { describe, expect, it } from "vitest";
import { HyperliquidAdapter } from "../src/venues/hyperliquid.js";

describe("Hyperliquid precision helpers", () => {
  it("rounds price to 5 sig figs / <=6 decimals", () => {
    expect(HyperliquidAdapter.roundPx(96_960)).toBe(96_960);
    expect(HyperliquidAdapter.roundPx(0.909)).toBeCloseTo(0.909, 6);
    expect(HyperliquidAdapter.roundPx(0)).toBe(0);
  });

  it("truncates size to lot precision (floor, never up)", () => {
    expect(HyperliquidAdapter.roundSize(0.123456, 3)).toBe(0.123);
    expect(HyperliquidAdapter.roundSize(2.9, 0)).toBe(2);
    expect(HyperliquidAdapter.roundSize(0.0004, 3)).toBe(0); // sub-lot -> 0
  });
});
