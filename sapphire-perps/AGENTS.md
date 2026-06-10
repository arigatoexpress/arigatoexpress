# AGENTS.md — fast path for Sapphire Perps

If you're an agent (or a human in a hurry) working in this repo, read this first.

## What this is
An automated perpetual-futures trading system. Signals → risk kernel → approval
gate → venue adapter. Paper-first, fail-closed, human-in-charge.

## Read these, in order
1. `src/sapphire_perps/types.py` — the vocabulary (Order, Position, Quote…).
2. `src/sapphire_perps/risk/kernel.py` — the safety chokepoint. Understand this
   before changing anything that places orders.
3. `src/sapphire_perps/execution/router.py` — the single path to a venue.
4. `src/sapphire_perps/venues/` — `base.py`, then `paper.py`, then the venue you
   care about.

## Dev commands
```bash
pip install -e ".[dev]"
pytest -q                 # offline, no SDK/network needed
ruff check src tests
python -m sapphire_perps.cli status
```

## Safety boundaries — do not cross without explicit human sign-off
- **Never** weaken the fail-closed posture: an order must be provably within all
  limits to be approved. Missing data ⇒ reject.
- **Never** default `allow_live` to true, or make `is_live` true without BOTH
  `exec_mode == live` AND `allow_live == true`.
- **Never** bypass the approval gate for live orders. The default gate denies.
- **Never** read secrets from config files or commit them. Env vars only;
  `.env` is git-ignored.
- **Never** set `supports_perps = True` on Robinhood until Robinhood actually
  offers perpetual futures.
- Keep the core importable with stdlib only — venue SDKs stay optional extras
  behind guarded imports, so tests run offline.

## Conventions
- `size` is always positive; direction lives in `side`.
- Notional is in USD (`base_currency`).
- Reductions/closes are marked `reduce_only` so they can't flip a position.
- New venues: implement `VenueAdapter`, back paper mode with `PaperBroker`,
  register in `venues/__init__.build_adapter`, and gate live behind config.

## Who to ask
Changes touching the risk kernel, the live execution path, or anything that can
move real capital need a human review before merge.
