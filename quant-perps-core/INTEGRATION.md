# Wiring quant-perps-core into quant-perps `server.ts`

Surgical changes — the React terminal, Gemini endpoints, backtest, alerts, and
the market-price loop stay as-is. Copy `quant-perps-core/src` into the repo as
`server/core` (or publish it and import it), then:

## 1. Build the engine from the current BotSetting
```ts
import {
  defaultConfig, buildRouter, Engine, CopyTradeSignal,
  riskLimitsFromSettings, type AppConfig,
} from "./core/index.js";

const USER_COLLATERAL_USD = 10_000; // same assumption as the original bot

let appConfig: AppConfig;
let router: ReturnType<typeof buildRouter>;
let engine: Engine;

function rebuildEngine() {
  appConfig = defaultConfig();
  appConfig.execMode = botSetting.isPaperTrading ? "paper" : "live";
  // allowLive stays false unless an operator explicitly clears it (env/secret).
  appConfig.allowLive = process.env.QP_ALLOW_LIVE === "true";
  appConfig.risk = riskLimitsFromSettings(
    botSetting.riskSettings,
    USER_COLLATERAL_USD,
  );
  router = buildRouter(appConfig);
  engine = new Engine(
    appConfig,
    router,
    new CopyTradeSignal(
      () => clonedTargets(),
      USER_COLLATERAL_USD,
      botSetting.riskSettings.maxPositionSizePercent,
      botSetting.riskSettings.maxLeverage,
    ),
    Object.keys(assetPrices),
    "hyperliquid",
  );
}
```
Call `rebuildEngine()` at startup and in the `POST /api/bot-config` handler.

## 2. Map tracked wallets → clone targets
```ts
import type { CloneTarget, Side } from "./core/index.js";

function clonedTargets(): Map<string, CloneTarget> {
  const targets = new Map<string, CloneTarget>();
  const wallets = botSetting.cloneMode === "ALL"
    ? trackedWallets
    : trackedWallets.filter((w) => botSetting.selectedWalletIds.includes(w.id));
  for (const w of wallets) {
    const p = w.activePosition;
    if (p) targets.set(p.asset, { side: p.side.toLowerCase() as Side, leverage: p.leverage });
  }
  return targets;
}
```

## 3. Route the bot actions through the engine/router
```ts
// was: handleBotAutoOpen(wallet, position) building a BotTrade directly
function handleBotAutoOpen() {
  for (const r of engine.step()) {
    if (r.status === "filled") recordBotTrade(r);     // existing UI plumbing
    else logRejected(r.reason);                       // surfaced in the terminal
  }
}

// manual execute / close also go through the router:
function botManualExecute(order) { return router.submit(order); }
function botClose(symbol)        { return router.close(symbol, "hyperliquid"); }
```

## 4. Pricing
Feed live marks into a `CallablePriceSource` (instead of the bundled static
book) so the paper broker tracks the same CoinGecko prices the UI already
fetches:
```ts
import { CallablePriceSource } from "./core/index.js";
const priceSource = new CallablePriceSource(
  "hyperliquid",
  (sym) => assetPrices[sym]?.price ?? null,
  2,
);
// pass priceSource into a PaperBroker-backed adapter when constructing it.
```

## Notes
- Default stays **paper**; live needs `isPaperTrading=false` **and**
  `QP_ALLOW_LIVE=true` **and** an approval gate — three independent switches.
- Replace `AutoDenyGate` with a `CallbackApprovalGate` that prompts in the
  terminal UI before any live order.
- Live venue routing (Hyperliquid/Lighter) is stubbed fail-closed; see the
  testnet hardening backlog before enabling.
