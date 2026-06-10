from sapphire_perps.config import AppConfig, RiskLimits
from sapphire_perps.engine import Engine
from sapphire_perps.execution.approval import AutoDenyGate
from sapphire_perps.execution.router import OrderRouter
from sapphire_perps.risk.kernel import RiskKernel
from sapphire_perps.signals.base import Intent
from sapphire_perps.signals.momentum import MomentumSignal
from sapphire_perps.types import Side
from sapphire_perps.venues.base import StaticPriceSource, VenueAdapter
from sapphire_perps.venues.paper import PaperBroker


class PaperVenue(VenueAdapter):
    name = "paper"
    supports_perps = True
    is_live = False

    def __init__(self):
        self.src = StaticPriceSource("paper", {"BTC": 100_000.0}, spread_bps=0.0)
        self.broker = PaperBroker("paper", self.src, starting_equity=1_000_000, slippage_bps=0.0)

    def get_quote(self, s):
        return self.broker.get_quote(s)

    def get_account(self):
        return self.broker.get_account()

    def get_positions(self):
        return self.broker.get_positions()

    def place_order(self, o):
        return self.broker.place_order(o)

    def close_position(self, s):
        return self.broker.close_position(s)


class AlwaysLongSignal:
    name = "always_long"

    def evaluate(self, quotes, account):
        return [Intent(s, Side.LONG, 10_000.0, "test") for s in quotes]


def build(cfg_signal):
    cfg = AppConfig(
        risk=RiskLimits(allowed_symbols=["BTC"], max_order_notional_usd=1_000_000,
                        max_position_notional_usd=5_000_000, max_total_notional_usd=10_000_000),
        default_venue="paper",
    )
    venue = PaperVenue()
    router = OrderRouter({"paper": venue}, RiskKernel(cfg.risk), cfg, AutoDenyGate())
    engine = Engine(cfg, router, cfg_signal, symbols=["BTC"], venue="paper")
    return engine, venue


def test_engine_opens_position_from_intent():
    engine, venue = build(AlwaysLongSignal())
    results = engine.step()
    assert any(r.ok for r in results)
    pos = venue.get_account().position_for("BTC")
    assert pos is not None
    assert pos.side is Side.LONG
    # target $10k / $100k = 0.1 BTC
    assert abs(pos.size - 0.1) < 1e-6


def test_engine_idempotent_when_at_target():
    engine, venue = build(AlwaysLongSignal())
    engine.step()
    size_after_first = venue.get_account().position_for("BTC").size
    engine.step()  # already at target -> no new order
    size_after_second = venue.get_account().position_for("BTC").size
    assert abs(size_after_first - size_after_second) < 1e-9


def test_engine_run_bounded_steps():
    engine, _ = build(MomentumSignal(fast=2, slow=3))
    engine.config.poll_interval_s = 0  # don't sleep in tests
    engine.run(max_steps=3)  # should not raise


class TargetSignal:
    """A signal whose target can be changed between steps."""

    name = "target"

    def __init__(self, side, notional):
        self.side, self.notional = side, notional

    def evaluate(self, quotes, account):
        return [Intent(s, self.side, self.notional, "test") for s in quotes]


def test_engine_flips_across_zero_to_reach_target():
    # +$10k long, then target -$5k short. The engine must flip (not reduce-only
    # close and silently drop the short), ending at a $5k short = 0.05 BTC.
    sig = TargetSignal(Side.LONG, 10_000.0)
    engine, venue = build(sig)
    engine.step()
    assert venue.get_account().position_for("BTC").side is Side.LONG

    sig.side, sig.notional = Side.SHORT, 5_000.0
    engine.step()
    pos = venue.get_account().position_for("BTC")
    assert pos is not None, "engine dropped the short instead of flipping"
    assert pos.side is Side.SHORT
    assert abs(pos.size - 0.05) < 1e-6  # $5k / $100k
