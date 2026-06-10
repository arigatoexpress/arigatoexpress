# quant-perps-core

A fail-closed perps **execution + risk core** in TypeScript, ported from the
hardened `sapphire-perps` engine. It's a **drop-in for `quant-perps`'s
`server.ts`**: it replaces the mock bot logic with a real risk kernel, order
router, paper broker, and venue adapters, while leaving the React terminal and
the Gemini endpoints untouched.

```
signal → intents → engine → Order → [ RISK KERNEL ] → [ approval gate ] → venue adapter
                                          │                  │                  │
                                    fail closed         live only         paper | live
```

## Why
quant-perps today fills trades at `assetPrices[asset].price` with no pre-trade
risk gate, no approval gate, and `isPaperTrading` as a bare boolean. This core
brings the safety model the terminal's `riskSettings` imply:

- **Two switches for live** — `execMode === "live"` **and** `allowLive`.
- **Risk kernel on every order** — per-order/position/total notional caps,
  effective-leverage cap (from notional/equity), symbol allow/deny lists,
  max-open-positions, and a daily-loss circuit breaker. Missing data ⇒ reject.
- **Human approval gate on live orders** — default gate denies.
- **Reduce-only safety, executable-price risk, marketable-limit rules, IOC live
  limits, venue precision rounding** — all carried over and tested.

## Use
```ts
import {
  defaultConfig, buildRouter, Engine, CopyTradeSignal,
  riskLimitsFromSettings,
} from "quant-perps-core";

const config = defaultConfig();                 // paper, fail-closed
config.risk = riskLimitsFromSettings(botSetting.riskSettings, 10_000);
const router = buildRouter(config);             // AutoDeny gate by default

// Clone a tracked wallet's exposure, risk-gated:
const signal = new CopyTradeSignal(
  () => trackedTargets(),   // Map<symbol, { side, leverage }>
  10_000,                   // collateral USD
  botSetting.riskSettings.maxPositionSizePercent,
  botSetting.riskSettings.maxLeverage,
);
const engine = new Engine(config, router, signal, ["BTC", "ETH", "SOL"]);
engine.step();              // one decision cycle
```

## Test
```bash
npm install
npm run typecheck   # tsc --noEmit
npm test            # vitest — 26 tests, no network/SDK needed
```

## Integration
See [`INTEGRATION.md`](./INTEGRATION.md) for the surgical `server.ts` wiring
(map `BotSetting` → config, route `handleBotAutoOpen/Close` through the engine).
Live Hyperliquid/Lighter routing is intentionally stubbed (fail-closed) pending
the testnet hardening pass — see the plan in the sapphire-perps PR.
