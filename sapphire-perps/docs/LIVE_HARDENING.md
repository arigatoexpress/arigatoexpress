# Live Hyperliquid hardening backlog

The offline test suite covers the full signal → risk → execution loop in paper
mode. The **live** Hyperliquid order path (`_live_*` in `venues/hyperliquid.py`,
marked `# pragma: no cover`) can't be exercised without the SDK + a funded
testnet account, so the items below are intentionally deferred to a dedicated
**testnet hardening pass** rather than patched blind against an automated
reviewer. None of these affect paper mode (the default) or the safety gates.

## Done (conservative handling already in place)
- **Reduce-only on market reductions** — live market reduce-only routes to an
  aggressive IOC limit with `reduce_only=True` (never `market_open`).
- **Price precision** — `_round_px` (5 sig figs, ≤6 decimals) applied to the
  reduce-only IOC price and to live limit prices.
- **Size/lot precision** — `_round_size` floors the size to the asset's
  `szDecimals` (cached from `meta`); sub-lot sizes are rejected.
- **Resting-order risk** — live limits are submitted **IOC**, not GTC, so no
  order rests unreserved and can later fill to breach caps (fail-closed).

## Open — for the testnet pass
1. **Per-asset tick/lot metadata, properly.** Replace the heuristic
   `_round_px`/`_round_size` with exact rules derived from `meta` per asset
   (tick size, `szDecimals`, `MAX_DECIMALS = 6 - szDecimals`). Verify against
   live rejects on testnet.
2. **Resting maker orders with reserved risk.** If/when GTC maker orders are
   wanted, add open-order accounting: fetch resting orders and include their
   potential fills in the risk kernel's projected notional/leverage, then it's
   safe to rest exposure. (Until then: IOC only.)
3. **Live fill/response parsing** against real SDK responses (partial fills,
   `error` shapes, oid handling) — currently best-effort.
4. **Builder/asset index + leverage setting** — confirm `market_open`/`order`
   asset resolution and any required `update_leverage` calls on testnet.

## Engine (not live-specific)
5. **Split reversals into close + open slices.** A signal reversal (e.g. +$5k
   long → −$5k short) currently emits a single ~$10k delta order, which the
   `max_order_notional` cap can reject even though a close slice + an open slice
   would each be valid. `_intent_to_order` should return a close (`reduce_only`)
   order plus an open order when the target crosses zero. (Behavioural; affects
   paper and live equally. Deferred with the rest to avoid churn; will be
   carried into the TypeScript port.)
