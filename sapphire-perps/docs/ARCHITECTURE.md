# Architecture

## Data flow

```
                ┌─────────────┐
   market data  │   Signal    │  emits Intents (target exposure in USD)
   ───────────► │ (momentum)  │
                └──────┬──────┘
                       │ intents
                ┌──────▼──────┐
                │   Engine    │  diffs intent vs current position → Order
                └──────┬──────┘
                       │ Order (size>0, side carries direction)
                ┌──────▼──────────────────────────────────────┐
                │              OrderRouter                     │
                │  1. resolve venue                            │
                │  2. get quote  → price                       │
                │  3. get account                              │
                │  4. RiskKernel.evaluate(...)  ── reject ───► │ OrderResult(REJECTED)
                │  5. if live: config.is_live? approval.request│
                │  6. adapter.place_order(order)               │
                └──────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼───────────────┐
   ┌────▼────┐    ┌────▼────┐     ┌────▼─────┐
   │Hyperliq.│    │ Lighter │     │Robinhood │
   │ adapter │    │ adapter │     │ adapter  │
   └────┬────┘    └────┬────┘     └────┬─────┘
        │ paper|live   │ paper        │ paper (perps disabled)
   ┌────▼─────────────────────────────────────┐
   │ PaperBroker (netting, slippage, PnL)      │  ← simulation backing
   └───────────────────────────────────────────┘
```

## Key design decisions

### Fail-closed everywhere
The system's default state is "do nothing real." `exec_mode` defaults to `paper`,
`allow_live` to `false`, the approval gate to `AutoDenyGate`, and the risk kernel
rejects on any missing input. To trade real money, an operator must deliberately
flip *three* independent things (mode, allow_live, an approving gate).

### One chokepoint
`OrderRouter.submit` is the only path from an `Order` to a venue. The risk kernel
and approval gate live there, so there's no way to reach a venue that skips them.
Adapters expose `place_order`, but the engine and CLI only ever call the router.

### Paper is a first-class backing, not a mock
`PaperBroker` is a real (if simplified) perp simulator: it nets positions,
averages entry on adds, realises PnL on reductions/flips, applies taker
slippage, and reports a margin-style account. Every venue adapter delegates to it
in paper mode, so the *same* code path is exercised whether paper or live.

### Venue SDKs are optional
Imports of `hyperliquid-python-sdk`, `eth-account`, `lighter-sdk` are local and
guarded. The core — types, config, risk, router, paper, engine — is stdlib-only,
so the full test suite runs offline and CI needs no API keys.

### Direction vs size
`Order.size` is always positive; `Order.side` (LONG/SHORT) carries direction.
`signed_size = side.sign * size`. This keeps risk math unambiguous and prevents a
class of "negative size" bugs.

## Extending

- **New signal:** implement the `Signal` protocol (`evaluate(quotes, account) ->
  list[Intent]`). The engine handles intent→order translation and rebalancing.
- **New venue:** subclass `VenueAdapter`, back paper mode with `PaperBroker`,
  register it in `venues/__init__.build_adapter`, and keep live behind
  `config.is_live` + an env-sourced credential check.
- **Persistence:** paper/live state is currently per-process. Add a state store
  behind `PaperBroker` (and an account cache for live) to survive restarts.
