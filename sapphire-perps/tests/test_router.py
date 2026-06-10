
from sapphire_perps.config import AppConfig, ExecMode, RiskLimits
from sapphire_perps.execution.approval import AutoApproveGate, AutoDenyGate
from sapphire_perps.execution.router import OrderRouter
from sapphire_perps.risk.kernel import RiskKernel
from sapphire_perps.types import Order, OrderStatus, OrderType, Side
from sapphire_perps.venues.base import StaticPriceSource, VenueAdapter
from sapphire_perps.venues.paper import PaperBroker


class FakePaperVenue(VenueAdapter):
    name = "fake"
    supports_perps = True
    is_live = False

    def __init__(self):
        src = StaticPriceSource("fake", {"BTC": 100_000.0}, spread_bps=0.0)
        self.broker = PaperBroker("fake", src, starting_equity=1_000_000, slippage_bps=0.0)

    def get_quote(self, symbol):
        return self.broker.get_quote(symbol)

    def get_account(self):
        return self.broker.get_account()

    def get_positions(self):
        return self.broker.get_positions()

    def place_order(self, order):
        return self.broker.place_order(order)

    def close_position(self, symbol):
        return self.broker.close_position(symbol)


class FakeLiveVenue(FakePaperVenue):
    name = "fakelive"
    is_live = True


def make_config(**kw):
    cfg = AppConfig(
        risk=RiskLimits(allowed_symbols=["BTC", "ETH"], max_order_notional_usd=1_000_000,
                        max_position_notional_usd=5_000_000, max_total_notional_usd=10_000_000),
        default_venue="fake",
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def make_router(cfg, venues, approval=None):
    return OrderRouter(
        venues=venues, risk=RiskKernel(cfg.risk), config=cfg,
        approval=approval or AutoDenyGate(),
    )


def test_paper_order_fills():
    cfg = make_config()
    router = make_router(cfg, {"fake": FakePaperVenue()})
    res = router.submit(Order("BTC", Side.LONG, 0.1))
    assert res.status is OrderStatus.FILLED


def test_risk_rejection_short_circuits():
    cfg = make_config()
    cfg.risk.allowed_symbols = ["ETH"]  # BTC now disallowed
    router = make_router(cfg, {"fake": FakePaperVenue()})
    res = router.submit(Order("BTC", Side.LONG, 0.1))
    assert res.status is OrderStatus.REJECTED
    assert "risk:" in res.reason


def test_unknown_venue_rejected():
    cfg = make_config()
    router = make_router(cfg, {"fake": FakePaperVenue()})
    res = router.submit(Order("BTC", Side.LONG, 0.1, venue="nope"))
    assert res.status is OrderStatus.REJECTED
    assert "not available" in res.reason


def test_live_blocked_when_system_not_cleared():
    # adapter is live, but config not cleared for live -> reject
    cfg = make_config(default_venue="fakelive")
    cfg.exec_mode = ExecMode.PAPER  # not live
    router = make_router(cfg, {"fakelive": FakeLiveVenue()}, approval=AutoApproveGate())
    res = router.submit(Order("BTC", Side.LONG, 0.1))
    assert res.status is OrderStatus.REJECTED
    assert "not cleared for live" in res.reason


def test_live_blocked_when_approval_denied():
    cfg = make_config(default_venue="fakelive")
    cfg.exec_mode = ExecMode.LIVE
    cfg.allow_live = True
    assert cfg.is_live
    router = make_router(cfg, {"fakelive": FakeLiveVenue()}, approval=AutoDenyGate())
    res = router.submit(Order("BTC", Side.LONG, 0.1))
    assert res.status is OrderStatus.REJECTED
    assert "approval denied" in res.reason


def test_live_allowed_when_cleared_and_approved():
    cfg = make_config(default_venue="fakelive")
    cfg.exec_mode = ExecMode.LIVE
    cfg.allow_live = True
    router = make_router(cfg, {"fakelive": FakeLiveVenue()}, approval=AutoApproveGate())
    res = router.submit(Order("BTC", Side.LONG, 0.1))
    assert res.status is OrderStatus.FILLED


def test_non_perp_venue_rejects_perp_order():
    cfg = make_config()

    class NoPerps(FakePaperVenue):
        name = "noperps"
        supports_perps = False

    router = make_router(cfg, {"fake": NoPerps()})
    res = router.submit(Order("BTC", Side.LONG, 0.1))
    assert res.status is OrderStatus.REJECTED
    assert "does not support perps" in res.reason


def test_market_risk_uses_executable_price():
    # Wide spread so ask >> mid. An order whose notional is under the cap at the
    # mid but over it at the ask must be rejected (risk uses the executable ask).
    cfg = make_config()
    cfg.risk.max_order_notional_usd = 10_000
    venue = FakePaperVenue()
    venue.broker.price_source = StaticPriceSource("fake", {"BTC": 100_000.0}, spread_bps=2_000)
    router = make_router(cfg, {"fake": venue})
    # spread_bps=2000 -> ask = 110,000. 0.0999 BTC is $9,990 at the mid (under
    # the $10k cap) but $10,989 at the ask (over) -> must reject on the ask.
    res = router.submit(Order("BTC", Side.LONG, 0.0999))
    assert res.status is OrderStatus.REJECTED
    assert "risk:" in res.reason


def test_marketable_short_limit_risk_checked_at_bid():
    # Sell limit below the bid is marketable and fills at the bid, not the limit.
    # Risk must use the bid so the notional cap can't be dodged with a low limit.
    cfg = make_config()
    cfg.risk.max_order_notional_usd = 9_500  # bid notional $10k must exceed this
    router = make_router(cfg, {"fake": FakePaperVenue()})  # bid == 100k (spread 0)
    res = router.submit(
        Order("BTC", Side.SHORT, 0.1, order_type=OrderType.LIMIT, limit_price=90_000)
    )
    assert res.status is OrderStatus.REJECTED
    assert "risk:" in res.reason


def test_close_blocked_on_live_adapter_when_not_cleared():
    # Live adapter but system not cleared for live -> close must be rejected
    # before reaching the venue, mirroring submit()'s two-switch gate.
    cfg = make_config(default_venue="fakelive")
    cfg.exec_mode = ExecMode.PAPER
    router = make_router(cfg, {"fakelive": FakeLiveVenue()}, approval=AutoApproveGate())
    res = router.close("BTC")
    assert res.status is OrderStatus.REJECTED
    assert "not cleared for live" in res.reason


def test_daily_loss_breaker_trips_from_derived_pnl():
    # The router must derive session PnL itself (no external caller feeding it).
    cfg = make_config()
    cfg.risk.daily_loss_limit_usd = 5_000
    venue = FakePaperVenue()
    router = make_router(cfg, {"fake": venue})

    # Open 1 BTC long @100k; baseline equity is captured here.
    assert router.submit(Order("BTC", Side.LONG, 1.0)).status is OrderStatus.FILLED

    # Price drops 10k -> unrealized -$10k, beyond the $5k daily loss limit.
    venue.broker.price_source.set_price("BTC", 90_000.0)

    # A new (non-reduce-only) order must now be blocked by the breaker...
    blocked = router.submit(Order("BTC", Side.LONG, 0.1))
    assert blocked.status is OrderStatus.REJECTED
    assert "daily loss" in blocked.reason

    # ...but a reduce-only de-risking order is still allowed through.
    reduce = router.submit(Order("BTC", Side.SHORT, 0.5, reduce_only=True))
    assert reduce.status is OrderStatus.FILLED
