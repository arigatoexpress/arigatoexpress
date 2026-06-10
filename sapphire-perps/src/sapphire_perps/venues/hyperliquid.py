"""Hyperliquid adapter — the primary perp venue.

This adapter is wired end-to-end against the official `hyperliquid-python-sdk`:

  * PAPER mode (default): real mid prices are pulled from Hyperliquid's public
    `Info` endpoint (read-only, no key needed) and fed into the PaperBroker, so
    the simulation tracks the live market. If the SDK or network is
    unavailable, it degrades gracefully to a static price book.
  * LIVE mode: orders are sent through the SDK's `Exchange` client using a
    wallet key read from the environment. Live is only reachable when the app
    config is fully cleared (`exec_mode=live` AND `allow_live=true`) — enforced
    by the router, and re-checked here as defence in depth.

Env vars for live:
  HYPERLIQUID_ACCOUNT_ADDRESS   - the account (or API wallet owner) address
  HYPERLIQUID_SECRET_KEY        - the API wallet private key (NEVER committed)
"""

from __future__ import annotations

import os

from ..types import (
    AccountState,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    Position,
    Quote,
    Side,
)
from .base import CallablePriceSource, StaticPriceSource, VenueAdapter
from .paper import PaperBroker

MAINNET_API = "https://api.hyperliquid.xyz"
TESTNET_API = "https://api.hyperliquid-testnet.xyz"

# Conservative offline fallback marks (USD), only used when the live Info
# endpoint can't be reached in paper mode.
_FALLBACK_PRICES = {
    "BTC": 96_000.0,
    "ETH": 3_400.0,
    "SOL": 180.0,
    "HYPE": 28.0,
    "ARB": 0.9,
}


class HyperliquidAdapter(VenueAdapter):
    name = "hyperliquid"
    supports_perps = True

    def __init__(self, config):
        self.config = config
        venue_cfg = config.venue("hyperliquid")
        self.testnet = venue_cfg.testnet
        self.base_url = TESTNET_API if self.testnet else MAINNET_API
        self.is_live = config.is_live
        self._info = None  # lazily constructed SDK Info client
        self._exchange = None  # lazily constructed SDK Exchange client

        if self.is_live:
            self._init_live()
        else:
            price_source = self._build_paper_price_source()
            self.broker = PaperBroker(
                venue=self.name,
                price_source=price_source,
                starting_equity=config.paper_starting_equity_usd,
                slippage_bps=config.paper_slippage_bps,
            )

    # ------------------------------------------------------------------
    # paper plumbing
    # ------------------------------------------------------------------
    def _build_paper_price_source(self):
        info = self._try_info()
        if info is None:
            return StaticPriceSource(self.name, _FALLBACK_PRICES, spread_bps=2.0)

        def live_mid(symbol: str) -> float | None:
            try:
                mids = info.all_mids()
                px = mids.get(symbol)
                return float(px) if px is not None else _FALLBACK_PRICES.get(symbol)
            except Exception:
                return _FALLBACK_PRICES.get(symbol)

        return CallablePriceSource(self.name, live_mid, spread_bps=2.0)

    def _try_info(self):
        """Return an SDK Info client, or None if SDK/network unavailable."""
        if self._info is not None:
            return self._info
        try:
            from hyperliquid.info import Info  # type: ignore
            from hyperliquid.utils import constants  # type: ignore

            url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
            self._info = Info(url, skip_ws=True)
        except Exception:
            self._info = None
        return self._info

    # ------------------------------------------------------------------
    # live plumbing
    # ------------------------------------------------------------------
    def _init_live(self) -> None:
        address = os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS")
        secret = os.getenv("HYPERLIQUID_SECRET_KEY")
        if not address or not secret:
            raise RuntimeError(
                "live Hyperliquid requires HYPERLIQUID_ACCOUNT_ADDRESS and "
                "HYPERLIQUID_SECRET_KEY in the environment"
            )
        try:
            from eth_account import Account  # type: ignore
            from hyperliquid.exchange import Exchange  # type: ignore
            from hyperliquid.info import Info  # type: ignore
            from hyperliquid.utils import constants  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "live Hyperliquid requires the SDK: "
                "`pip install sapphire-perps[hyperliquid]`"
            ) from exc

        url = constants.TESTNET_API_URL if self.testnet else constants.MAINNET_API_URL
        wallet = Account.from_key(secret)
        self._info = Info(url, skip_ws=True)
        self._exchange = Exchange(wallet, url, account_address=address)
        self._address = address

    # ------------------------------------------------------------------
    # VenueAdapter interface
    # ------------------------------------------------------------------
    def get_quote(self, symbol: str) -> Quote | None:
        if not self.is_live:
            return self.broker.get_quote(symbol)
        info = self._info
        try:
            mids = info.all_mids()  # type: ignore[union-attr]
            mid = float(mids[symbol])
        except Exception:
            return None
        spread = mid * 1e-4  # ~1bp synthetic spread for a top-of-book estimate
        return Quote(symbol=symbol, venue=self.name, bid=mid - spread, ask=mid + spread)

    def get_positions(self) -> list[Position]:
        if not self.is_live:
            return self.broker.get_positions()
        return self._live_positions()

    def get_account(self) -> AccountState:
        if not self.is_live:
            return self.broker.get_account()
        return self._live_account()

    def place_order(self, order: Order) -> OrderResult:
        if not self.is_live:
            return self.broker.place_order(order)
        return self._live_place_order(order)

    def close_position(self, symbol: str) -> OrderResult:
        if not self.is_live:
            return self.broker.close_position(symbol)
        try:
            resp = self._exchange.market_close(symbol)  # type: ignore[union-attr]
            return self._parse_response(
                Order(symbol=symbol, side=Side.SHORT, size=1.0, reduce_only=True), resp
            )
        except Exception as exc:  # pragma: no cover - network path
            dummy = Order(symbol=symbol, side=Side.SHORT, size=1.0, reduce_only=True)
            return OrderResult(dummy, OrderStatus.REJECTED, self.name, reason=str(exc))

    # ------------------------------------------------------------------
    # live helpers (network paths — not exercised by the offline test suite)
    # ------------------------------------------------------------------
    def _live_place_order(self, order: Order) -> OrderResult:  # pragma: no cover
        ex = self._exchange
        is_buy = order.side is Side.LONG
        slippage = 0.01  # 1% marketable band
        try:
            if order.order_type is OrderType.MARKET and not order.reduce_only:
                resp = ex.market_open(order.symbol, is_buy, order.size, None, slippage)
            elif order.order_type is OrderType.MARKET and order.reduce_only:
                # `market_open` does NOT carry reduce_only, so a market reduce
                # could flip/increase the position. Instead send an aggressive
                # IOC limit with reduce_only=True so the venue enforces it.
                mid = float(self._info.all_mids()[order.symbol])
                px = mid * (1 + slippage) if is_buy else mid * (1 - slippage)
                # NOTE: production should round px to the asset's tick size.
                resp = ex.order(
                    order.symbol, is_buy, order.size, px,
                    {"limit": {"tif": "Ioc"}}, reduce_only=True,
                )
            else:
                resp = ex.order(
                    order.symbol,
                    is_buy,
                    order.size,
                    order.limit_price,
                    {"limit": {"tif": "Gtc"}},
                    reduce_only=order.reduce_only,
                )
            return self._parse_response(order, resp)
        except Exception as exc:
            return OrderResult(order, OrderStatus.REJECTED, self.name, reason=str(exc))

    def _parse_response(self, order: Order, resp: dict) -> OrderResult:  # pragma: no cover
        try:
            statuses = resp["response"]["data"]["statuses"]
            first = statuses[0]
            if "filled" in first:
                f = first["filled"]
                return OrderResult(
                    order=order,
                    status=OrderStatus.FILLED,
                    venue=self.name,
                    filled_size=float(f["totalSz"]),
                    avg_price=float(f["avgPx"]),
                    venue_order_id=str(f.get("oid", "")),
                )
            if "resting" in first:
                return OrderResult(
                    order=order,
                    status=OrderStatus.PENDING,
                    venue=self.name,
                    venue_order_id=str(first["resting"].get("oid", "")),
                )
            return OrderResult(
                order, OrderStatus.REJECTED, self.name,
                reason=str(first.get("error", first)),
            )
        except Exception as exc:
            return OrderResult(order, OrderStatus.REJECTED, self.name, reason=f"unparseable response: {exc}")

    def _live_positions(self) -> list[Position]:  # pragma: no cover
        state = self._info.user_state(self._address)  # type: ignore[union-attr]
        out: list[Position] = []
        for ap in state.get("assetPositions", []):
            p = ap.get("position", {})
            szi = float(p.get("szi", 0) or 0)
            if szi == 0:
                continue
            out.append(
                Position(
                    symbol=p["coin"],
                    venue=self.name,
                    side=Side.LONG if szi > 0 else Side.SHORT,
                    size=abs(szi),
                    entry_price=float(p.get("entryPx", 0) or 0),
                    mark_price=float(p.get("entryPx", 0) or 0),
                    leverage=float(p.get("leverage", {}).get("value", 1) or 1),
                )
            )
        return out

    def _live_account(self) -> AccountState:  # pragma: no cover
        state = self._info.user_state(self._address)  # type: ignore[union-attr]
        summary = state.get("marginSummary", {})
        equity = float(summary.get("accountValue", 0) or 0)
        positions = self._live_positions()
        used = float(summary.get("totalMarginUsed", 0) or 0)
        return AccountState(
            venue=self.name,
            equity=equity,
            free_collateral=max(0.0, equity - used),
            positions=positions,
        )
