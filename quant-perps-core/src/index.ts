// Public surface for the quant-perps execution/risk core.
export * from "./types.js";
export * from "./config.js";
export { RiskKernel, type RiskDecision } from "./risk/kernel.js";
export {
  type ApprovalGate,
  AutoDenyGate,
  AutoApproveGate,
  CallbackApprovalGate,
} from "./execution/approval.js";
export { OrderRouter } from "./execution/router.js";
export {
  type VenueAdapter,
  type PriceSource,
  StaticPriceSource,
  CallablePriceSource,
  describeVenue,
} from "./venues/base.js";
export { PaperBroker } from "./venues/paper.js";
export { HyperliquidAdapter } from "./venues/hyperliquid.js";
export { LighterAdapter } from "./venues/lighter.js";
export {
  RobinhoodAdapter,
  mapRobinhoodAccount,
  type RobinhoodClient,
  type RobinhoodSnapshot,
} from "./venues/robinhood.js";
export { type Intent, type Signal, signedTarget } from "./signals/base.js";
export { CopyTradeSignal, type CloneTarget } from "./signals/copyTrade.js";
export { Engine } from "./engine.js";

import type { AppConfig } from "./config.js";
import { RiskKernel } from "./risk/kernel.js";
import { OrderRouter } from "./execution/router.js";
import { type ApprovalGate, AutoDenyGate } from "./execution/approval.js";
import type { VenueAdapter } from "./venues/base.js";
import { HyperliquidAdapter } from "./venues/hyperliquid.js";
import { LighterAdapter } from "./venues/lighter.js";

// Build the default venue set for a config (paper unless cleared for live).
export function buildAdapters(config: AppConfig): Map<string, VenueAdapter> {
  const adapters = new Map<string, VenueAdapter>();
  adapters.set("hyperliquid", new HyperliquidAdapter(config));
  adapters.set("lighter", new LighterAdapter(config));
  return adapters;
}

export function buildRouter(
  config: AppConfig,
  approval: ApprovalGate = new AutoDenyGate(),
  adapters: Map<string, VenueAdapter> = buildAdapters(config),
): OrderRouter {
  return new OrderRouter(adapters, new RiskKernel(config.risk), config, approval);
}
