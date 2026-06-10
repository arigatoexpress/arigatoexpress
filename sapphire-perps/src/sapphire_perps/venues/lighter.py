"""Lighter (zkLighter) adapter — second perp venue.

Status: PAPER fully functional via the shared PaperBroker; LIVE is a guarded
stub. The live path documents exactly what the `lighter-sdk` integration needs
so it can be filled in without re-architecting.

Live wiring outline (see https://github.com/elliottech/lighter-python):
    import lighter
    client = lighter.SignerClient(url=..., private_key=..., account_index=...,
                                  api_key_index=...)
    client.create_order(market_index=..., client_order_index=..., base_amount=...,
                        price=..., is_ask=..., order_type=...)

Env vars (live, NEVER committed):
  LIGHTER_API_KEY_PRIVATE_KEY
  LIGHTER_ACCOUNT_INDEX
  LIGHTER_API_KEY_INDEX
"""

from __future__ import annotations

from ..types import AccountState, Order, OrderResult, Position, Quote
from .base import StaticPriceSource, VenueAdapter
from .paper import PaperBroker

_FALLBACK_PRICES = {"BTC": 96_000.0, "ETH": 3_400.0, "SOL": 180.0}


class LighterAdapter(VenueAdapter):
    name = "lighter"
    supports_perps = True

    def __init__(self, config):
        self.config = config
        venue_cfg = config.venue("lighter")
        self.testnet = venue_cfg.testnet
        self.is_live = config.is_live
        if self.is_live:
            # Fail closed: don't pretend we can route real Lighter orders yet.
            raise NotImplementedError(
                "Lighter live trading is not wired yet. Run in paper mode, or "
                "implement SignerClient order routing in LighterAdapter._live_*."
            )
        self.broker = PaperBroker(
            venue=self.name,
            price_source=StaticPriceSource(self.name, _FALLBACK_PRICES, spread_bps=3.0),
            starting_equity=config.paper_starting_equity_usd,
            slippage_bps=config.paper_slippage_bps,
        )

    def get_quote(self, symbol: str) -> Quote | None:
        return self.broker.get_quote(symbol)

    def get_account(self) -> AccountState:
        return self.broker.get_account()

    def get_positions(self) -> list[Position]:
        return self.broker.get_positions()

    def place_order(self, order: Order) -> OrderResult:
        return self.broker.place_order(order)

    def close_position(self, symbol: str) -> OrderResult:
        return self.broker.close_position(symbol)
