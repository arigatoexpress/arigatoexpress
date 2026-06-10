"""Robinhood Agentic adapter — equities today, perps "coming soon".

Robinhood launched Agentic Trading (May 2026) exposed over an MCP server at
`https://agent.robinhood.com/mcp/trading`. As of this build it supports
**equities only**; crypto / futures / event contracts are announced but not
live, and perpetual futures are not yet offered.

Consequences for this system:
  * `supports_perps = False` — the router will refuse to send perp orders here,
    so we never silently misroute.
  * The adapter is structured so that, when Robinhood enables perps, wiring is
    a matter of flipping `supports_perps` and implementing the MCP tool calls
    in `_live_*` (the agent reaches the MCP endpoint; this process does not hold
    Robinhood credentials directly — auth happens through Robinhood's flow).

Paper mode is supported for end-to-end loop testing with a static book.
"""

from __future__ import annotations

from ..types import AccountState, Order, OrderResult, OrderStatus, Position, Quote
from .base import StaticPriceSource, VenueAdapter
from .paper import PaperBroker

MCP_ENDPOINT = "https://agent.robinhood.com/mcp/trading"

# Equity reference marks for paper testing (Robinhood is equities-only today).
_FALLBACK_PRICES = {"AAPL": 220.0, "NVDA": 140.0, "SPY": 560.0}


class RobinhoodAdapter(VenueAdapter):
    name = "robinhood"
    # Perps not offered by Robinhood Agentic yet — keep this False until they are.
    supports_perps = False

    def __init__(self, config):
        self.config = config
        self.is_live = config.is_live
        if self.is_live:
            raise NotImplementedError(
                "Robinhood Agentic trading is reached via its MCP endpoint "
                f"({MCP_ENDPOINT}) and currently supports equities only. Perp "
                "routing is disabled until Robinhood ships crypto perps."
            )
        self.broker = PaperBroker(
            venue=self.name,
            price_source=StaticPriceSource(self.name, _FALLBACK_PRICES, spread_bps=1.0),
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
        if not self.supports_perps:
            # Defence in depth — the router also checks this.
            return OrderResult(
                order=order,
                status=OrderStatus.REJECTED,
                venue=self.name,
                reason="Robinhood Agentic does not offer perps yet",
            )
        return self.broker.place_order(order)  # pragma: no cover

    def close_position(self, symbol: str) -> OrderResult:
        return self.broker.close_position(symbol)
