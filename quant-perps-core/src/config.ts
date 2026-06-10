import type { ExecMode } from "./types.js";

// Hard pre-trade limits. Any breach => order rejected (fail closed).
export interface RiskLimits {
  maxOrderNotionalUsd: number;
  minOrderNotionalUsd: number;
  maxPositionNotionalUsd: number;
  maxTotalNotionalUsd: number;
  maxLeverage: number;
  maxOpenPositions: number;
  dailyLossLimitUsd: number;
  allowedSymbols: string[]; // empty => allow any not blacklisted
  blacklistSymbols: string[];
}

export interface AppConfig {
  execMode: ExecMode;
  allowLive: boolean; // live requires execMode==="live" AND allowLive
  defaultVenue: string;
  paperStartingEquityUsd: number;
  paperSlippageBps: number;
  risk: RiskLimits;
}

export const isLive = (c: AppConfig): boolean =>
  c.execMode === "live" && c.allowLive;

export function defaultRiskLimits(): RiskLimits {
  return {
    maxOrderNotionalUsd: 5_000,
    minOrderNotionalUsd: 10,
    maxPositionNotionalUsd: 25_000,
    maxTotalNotionalUsd: 100_000,
    maxLeverage: 10,
    maxOpenPositions: 5,
    dailyLossLimitUsd: 2_000,
    allowedSymbols: ["BTC", "ETH", "SOL"],
    blacklistSymbols: [],
  };
}

export function defaultConfig(): AppConfig {
  return {
    execMode: "paper",
    allowLive: false,
    defaultVenue: "hyperliquid",
    paperStartingEquityUsd: 100_000,
    paperSlippageBps: 2,
    risk: defaultRiskLimits(),
  };
}

// ---- bridge from quant-perps' BotSetting.riskSettings -------------------
// Mirrors src/types.ts RiskSettings in the quant-perps repo.
export interface QuantRiskSettings {
  maxLeverage: number;
  dailyStopLossPercent: number;
  maxDrawdownPercent: number;
  maxPositionSizePercent: number;
  blacklistAssets: string[];
}

// Translate the UI's percentage-based settings into absolute USD caps given
// the account's equity, preserving the existing knobs the terminal exposes.
export function riskLimitsFromSettings(
  rs: QuantRiskSettings,
  equityUsd: number,
): RiskLimits {
  const base = defaultRiskLimits();
  const maxPositionNotional =
    equityUsd * (rs.maxPositionSizePercent / 100) * rs.maxLeverage;
  return {
    ...base,
    maxLeverage: rs.maxLeverage,
    dailyLossLimitUsd: equityUsd * (rs.dailyStopLossPercent / 100),
    maxOrderNotionalUsd: maxPositionNotional,
    maxPositionNotionalUsd: maxPositionNotional,
    maxTotalNotionalUsd:
      equityUsd * (rs.maxDrawdownPercent / 100 + 1) * rs.maxLeverage,
    allowedSymbols: [], // allow any symbol not blacklisted
    blacklistSymbols: rs.blacklistAssets ?? [],
  };
}

export function validateConfig(c: AppConfig): void {
  const r = c.risk;
  if (r.minOrderNotionalUsd <= 0)
    throw new Error("risk.minOrderNotionalUsd must be > 0");
  if (r.maxOrderNotionalUsd < r.minOrderNotionalUsd)
    throw new Error("maxOrderNotional must be >= minOrderNotional");
  if (r.maxPositionNotionalUsd < r.maxOrderNotionalUsd)
    throw new Error("maxPositionNotional must be >= maxOrderNotional");
  if (r.maxTotalNotionalUsd < r.maxPositionNotionalUsd)
    throw new Error("maxTotalNotional must be >= maxPositionNotional");
  if (r.maxLeverage <= 0) throw new Error("maxLeverage must be > 0");
}
