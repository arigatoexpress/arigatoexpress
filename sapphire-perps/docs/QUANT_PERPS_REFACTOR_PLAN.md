# quant-perps refactor plan

Goal: replace the mock bot logic in `arigatoexpress/quant-perps` (Gemini AI
Studio app — React 19 + Vite + Tailwind + Express `server.ts`) with a real,
fail-closed execution/risk core ported from `sapphire-perps`, **keeping the
React terminal and the Gemini endpoints intact**. Blocked only on adding
`quant-perps` to the session's repo scope.

## What quant-perps has today
- `server.ts` (Express): tracked-wallet copy-trading bot with `handleBotAutoOpen`
  / `handleBotAutoClose`, `riskSettings`, backtest, alerts, 3 Gemini endpoints.
- `src/types.ts`: `Position`, `Wallet`, `BotTrade`, `RiskSettings`, `BotSetting`,
  `MarketPrice`, etc. (`LONG`/`SHORT`, `Hyperliquid`/`Lighter`).
- All trading is **mock**: fills at `assetPrices[asset].price`, no slippage, no
  pre-trade risk gate, no approval gate. `isPaperTrading` is a bare boolean.

## Target structure (new, TypeScript / ESM to match `"type":"module"`)
```
server/core/
  types.ts            # Side, OrderType, TimeInForce, ExecMode, Order, OrderResult,
                      # Quote, AccountState — reusing src/types.ts Position/Wallet
  config.ts           # AppConfig + RiskLimits (built from BotSetting.riskSettings),
                      # execMode + allowLive (the two-switch live gate)
  risk/kernel.ts      # RiskKernel.evaluate(order, price, account, dailyPnl)
  execution/
    router.ts         # resolve venue -> executable price -> risk -> approval -> adapter
    approval.ts       # AutoDeny (default) / callback / auto gates
  venues/
    base.ts           # VenueAdapter + PriceSource
    paper.ts          # PaperBroker (netting, PnL, slippage, marketable-limit rules)
    hyperliquid.ts    # paper now; live via a TS HL SDK later (IOC limits)
    lighter.ts        # paper now; live stub
  signals/
    copyTrade.ts      # tracked-wallet Position -> Intent[] (replaces inline clone sizing)
  engine.ts           # clone loop: diff tracked vs bot position -> risk-checked orders
server/__tests__/     # vitest: kernel, paper broker, router, engine (port the 52 tests)
```

## Mapping (their model -> ported core)
| quant-perps | ported core |
|---|---|
| `RiskSettings.maxLeverage` | `RiskLimits.maxLeverage` (enforced from notional/equity, not opt-in) |
| `RiskSettings.dailyStopLossPercent` | daily-loss breaker vs session equity baseline (% of equity) |
| `RiskSettings.maxPositionSizePercent` | `maxPositionNotional` = pct × equity |
| `RiskSettings.maxDrawdownPercent` | new drawdown breaker (peak-equity tracking) |
| `RiskSettings.blacklistAssets` | denylist (inverse of `allowedSymbols`) |
| `BotSetting.isPaperTrading` | `execMode` (paper/live) — live also needs `allowLive` |
| `handleBotAutoOpen` | `copyTrade` signal -> `Intent` -> `engine` -> `router.submit` |
| `handleBotAutoClose` | engine emits `reduce_only` close when tracked wallet exits |
| mock fill at `price` | `PaperBroker` fill at book +/- slippage; marketable-limit rules |

## Hardened behaviors to carry over (from the sapphire-perps review rounds)
1. `size > 0`, direction via `side`; signed-size math.
2. Fail-closed risk: missing price/account/equity => reject.
3. Reduce-only validity: requires an opposite-side position; else reject.
4. Leverage enforced from post-trade notional / equity (not an opt-in field).
5. Daily-loss circuit breaker derived from a per-venue session equity baseline;
   reduce-only still allowed when tripped.
6. Two-switch live gate (`execMode=live` AND `allowLive`) + human approval, on
   both open and close paths.
7. Risk evaluated at the worst-case executable price (ask for buys, bid for
   sells); engine sizes at the same price so cap-hugging targets don't trip.
8. Marketable limits fill at the book capped by limit; non-marketable rest.
9. Live HL: IOC limits (no unreserved resting), price + size rounded to
   tick/`szDecimals`. (See LIVE_HARDENING.md for the testnet backlog.)
10. Crossing-zero targets flip via close+open rather than a mis-marked
    reduce-only; reversal-split is the one open engine item (LIVE_HARDENING #5).

## server.ts integration (minimal, surgical)
- Build one `AppConfig`/`RiskKernel`/`OrderRouter`/`Engine` at startup from the
  current `BotSetting`; rebuild on `POST /api/bot-config`.
- `handleBotAutoOpen(wallet, pos)` -> `engine.cloneOpen(wallet, pos)` which makes
  an `Intent` and routes a risk-checked order; push the resulting `BotTrade`.
- `handleBotAutoClose(wallet, pos)` -> `engine.cloneClose(...)` -> reduce-only.
- `/api/bot-manual-execute` and `/api/bot-trades/close` go through the router too.
- Gemini endpoints, backtest, alerts, market-price loop: **unchanged**.
- Keep paper as default; live requires env creds + `allowLive` + approval.

## Tooling
- Add `vitest` (they have no test runner) + a `test` script; CI workflow at the
  repo root this time (it's the project's own repo).
- Live HL SDK (e.g. a TS Hyperliquid client) added only behind the live path;
  paper needs no new runtime deps.

## Rollout
1. Land `server/core/*` + tests (paper-only) with the bot wired through it.
2. Verify the existing UI still drives the bot (clone/close/manual) on paper.
3. Hyperliquid/Lighter live behind the two-switch gate, per LIVE_HARDENING.md.
