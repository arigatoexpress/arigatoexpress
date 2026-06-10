<div align="center">

# Sapphire Perps

**An automated perpetual-futures trading system — risk kernel, signal layer, and multi-venue execution.**

Paper-first · fail-closed · human stays in charge.

</div>

---

## What this is

A clean, from-scratch rebuild of an automated perps trading stack. Signals
generate intents, a risk kernel vets every order, and an execution router sends
them to one of several perp venues — or simulates them. Real money is reachable
only behind two independent switches *and* a human approval gate.

```
signal ──> intents ──> engine ──> Order ──> [ RISK KERNEL ] ──> [ approval gate ] ──> venue adapter
                                                  │                    │                     │
                                            fail closed          live only            paper | live
```

### Venues

| Venue | Perps? | Paper | Live | Notes |
|---|---|---|---|---|
| **Hyperliquid** | ✅ | ✅ (live marks from public API) | ✅ (testnet/mainnet, SDK) | Primary venue, wired end-to-end. |
| **Lighter (zkLighter)** | ✅ | ✅ | ⏳ stub | Paper works; live `SignerClient` routing is a documented TODO. |
| **Robinhood Agentic** | ❌ *(equities only today)* | ✅ | ⛔ blocked | Reached via [`agent.robinhood.com/mcp/trading`](https://robinhood.com/us/en/agentic-trading/). Perps not offered yet — router refuses to misroute. Flip `supports_perps` when RH ships them. |

## Quickstart

```bash
git clone <this-repo> && cd sapphire-perps
pip install -e ".[dev]"            # core + pytest/ruff
# (optional) live Hyperliquid: pip install -e ".[hyperliquid]"

# Everything below is paper mode by default.
sapphire-perps status
sapphire-perps quote BTC
sapphire-perps trade BTC long 0.02
sapphire-perps run --steps 5       # run the engine loop a few cycles
```

## Safety model (fail-closed by design)

1. **Two switches for live.** Orders go real only when `exec_mode: live` **and**
   `allow_live: true`. Defaults are paper + false. (`AppConfig.is_live`.)
2. **Every order passes the risk kernel.** Notional caps (per-order, per-position,
   total), leverage cap, symbol allowlist, max open positions, and a daily-loss
   circuit breaker. Missing price or account data ⇒ **reject**, never pass.
3. **Human approval gate on live orders.** The default gate *denies*. Live runs
   use an interactive y/N prompt. Reduce-only/close still passes the gate.
4. **Secrets only from the environment.** Never read from config files; `.env` is
   git-ignored. See [`.env.example`](.env.example).
5. **Reduce-only safety.** Shrinking/closing orders are marked `reduce_only` so a
   rebalance can't accidentally flip into a larger opposite position.

## Project layout

```
src/sapphire_perps/
├── types.py            # domain types: Order, Position, Quote, AccountState…
├── config.py           # layered config (defaults < file < env), fail-closed
├── risk/kernel.py      # the one chokepoint: pre-trade limit checks
├── signals/            # Signal protocol + dual-SMA momentum reference signal
├── execution/
│   ├── router.py       # resolve venue → price → risk → approval → adapter
│   └── approval.py     # AutoDeny (default) / CLI prompt / AutoApprove gates
├── venues/
│   ├── base.py         # VenueAdapter ABC + price sources
│   ├── paper.py        # in-memory perp simulation (netting, PnL, slippage)
│   ├── hyperliquid.py  # primary venue, wired to the SDK
│   ├── lighter.py      # paper + live stub
│   └── robinhood.py    # equities-only adapter (perps disabled)
├── engine.py           # signal → intent → order loop
├── bootstrap.py        # build adapters/router/engine from config
└── cli.py              # argparse CLI (status/quote/positions/trade/run)
```

## Testing

```bash
pytest -q          # 33 tests, no network or SDK required
ruff check src tests
```

The whole core (risk kernel, paper broker, router, engine) runs offline with
stdlib only — the venue SDKs are optional extras pulled in solely for live runs.

## Status & roadmap

- [x] Risk kernel, paper broker, router, engine, CLI, tests, CI
- [x] Hyperliquid adapter (paper marks live; live order path via SDK)
- [ ] Persist paper/live state across processes (currently per-process in-memory)
- [ ] Lighter live `SignerClient` order routing
- [ ] Robinhood perps (blocked on Robinhood shipping crypto perps)
- [ ] Funding-rate carry into PnL; websocket market data; backtester

> ⚠️ Trading perpetual futures is high-risk. This software is provided as-is with
> no warranty. Run on paper/testnet and read the code before risking capital.
