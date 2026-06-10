"""Command-line interface (stdlib argparse — no third-party CLI dependency).

    sapphire-perps status
    sapphire-perps quote BTC
    sapphire-perps positions
    sapphire-perps trade BTC long 0.01 --venue hyperliquid
    sapphire-perps run --steps 5

All commands default to paper mode. Live requires `exec_mode=live` and
`allow_live=true` in config/env, and trades pass through the approval gate.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .bootstrap import build_engine, build_router
from .config import AppConfig, load_config
from .types import Order, OrderType, Side

DEFAULT_CONFIG = "config/default.yaml"


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _print_banner(cfg: AppConfig) -> None:
    mode = "LIVE 🔴" if cfg.is_live else "paper 🟢"
    print(f"sapphire-perps — mode={mode}  default_venue={cfg.default_venue}")


def cmd_status(cfg: AppConfig, args: argparse.Namespace) -> int:
    _print_banner(cfg)
    router = build_router(cfg)
    print("\nVenues:")
    for name in cfg.venues:
        adapter = router.venues.get(name)
        if adapter is None:
            state = "disabled" if not cfg.venue(name).enabled else "unavailable"
            print(f"  - {name}: {state}")
        else:
            print(f"  - {adapter.describe()}")
    r = cfg.risk
    print("\nRisk limits:")
    print(f"  max order notional:    ${r.max_order_notional_usd:,.0f}")
    print(f"  max position notional: ${r.max_position_notional_usd:,.0f}")
    print(f"  max total notional:    ${r.max_total_notional_usd:,.0f}")
    print(f"  max leverage:          {r.max_leverage}x")
    print(f"  max open positions:    {r.max_open_positions}")
    print(f"  daily loss limit:      ${r.daily_loss_limit_usd:,.0f}")
    print(f"  allowed symbols:       {', '.join(r.allowed_symbols)}")
    return 0


def cmd_quote(cfg: AppConfig, args: argparse.Namespace) -> int:
    router = build_router(cfg)
    venue = args.venue or cfg.default_venue
    adapter = router.venues.get(venue)
    if adapter is None:
        print(f"venue {venue!r} not available", file=sys.stderr)
        return 2
    q = adapter.get_quote(args.symbol)
    if q is None:
        print(f"no quote for {args.symbol} on {venue}", file=sys.stderr)
        return 1
    print(f"{args.symbol}@{venue}  bid={q.bid:,.2f}  ask={q.ask:,.2f}  "
          f"mid={q.mid:,.2f}  spread={q.spread_bps:.1f}bps")
    return 0


def cmd_positions(cfg: AppConfig, args: argparse.Namespace) -> int:
    router = build_router(cfg)
    venue = args.venue or cfg.default_venue
    adapter = router.venues.get(venue)
    if adapter is None:
        print(f"venue {venue!r} not available", file=sys.stderr)
        return 2
    account = adapter.get_account()
    print(f"{venue}  equity=${account.equity:,.2f}  "
          f"free=${account.free_collateral:,.2f}")
    if not account.positions:
        print("  (no open positions)")
        return 0
    for p in account.positions:
        print(f"  {p.side.value:>5} {p.size:g} {p.symbol} @ {p.entry_price:,.2f} "
              f"mark {p.mark:,.2f}  uPnL ${p.unrealized_pnl:,.2f}")
    return 0


def cmd_trade(cfg: AppConfig, args: argparse.Namespace) -> int:
    router = build_router(cfg)
    side = Side(args.side.lower())
    order = Order(
        symbol=args.symbol,
        side=side,
        size=args.size,
        order_type=OrderType.LIMIT if args.limit else OrderType.MARKET,
        limit_price=args.limit,
        reduce_only=args.reduce_only,
        venue=args.venue or cfg.default_venue,
    )
    result = router.submit(order)
    status_icon = "✅" if result.ok else "⛔"
    print(f"{status_icon} {result.status.value}: {order.side.value} {order.size} "
          f"{order.symbol} on {result.venue}")
    if result.ok:
        print(f"   filled {result.filled_size:g} @ {result.avg_price:,.2f} "
              f"(${result.notional:,.2f})")
    else:
        print(f"   reason: {result.reason}")
    return 0 if result.ok else 1


def cmd_run(cfg: AppConfig, args: argparse.Namespace) -> int:
    engine = build_engine(cfg)
    engine.run(max_steps=args.steps)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sapphire-perps", description=__doc__)
    p.add_argument("-c", "--config", default=DEFAULT_CONFIG, help="config file path")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--venue", help="override venue for this command")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show config, venues, and risk limits")

    sp = sub.add_parser("quote", help="get a quote")
    sp.add_argument("symbol")

    sub.add_parser("positions", help="list open positions")

    sp = sub.add_parser("trade", help="submit an order (paper unless live cleared)")
    sp.add_argument("symbol")
    sp.add_argument("side", choices=["long", "short"])
    sp.add_argument("size", type=float)
    sp.add_argument("--limit", type=float, help="limit price (omit for market)")
    sp.add_argument("--reduce-only", action="store_true")

    sp = sub.add_parser("run", help="run the engine loop")
    sp.add_argument("--steps", type=int, default=None, help="number of steps (default: forever)")

    return p


_COMMANDS = {
    "status": cmd_status,
    "quote": cmd_quote,
    "positions": cmd_positions,
    "trade": cmd_trade,
    "run": cmd_run,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    cfg = load_config(args.config)
    return _COMMANDS[args.command](cfg, args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
