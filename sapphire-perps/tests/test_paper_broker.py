import pytest

from sapphire_perps.types import Order, OrderStatus, OrderType, Side
from sapphire_perps.venues.base import StaticPriceSource
from sapphire_perps.venues.paper import PaperBroker


@pytest.fixture
def broker():
    src = StaticPriceSource("paper", {"BTC": 100_000.0, "ETH": 3_000.0}, spread_bps=0.0)
    return PaperBroker("paper", src, starting_equity=1_000_000.0, slippage_bps=0.0)


def test_open_long_creates_position(broker):
    res = broker.place_order(Order("BTC", Side.LONG, 0.5))
    assert res.status is OrderStatus.FILLED
    pos = broker.get_account().position_for("BTC")
    assert pos.side is Side.LONG
    assert pos.size == 0.5
    assert pos.entry_price == 100_000.0


def test_averaging_up_blends_entry(broker):
    broker.place_order(Order("BTC", Side.LONG, 1.0))  # @100k
    src = broker.price_source
    src.set_price("BTC", 120_000.0)
    broker.place_order(Order("BTC", Side.LONG, 1.0))  # @120k
    pos = broker.get_account().position_for("BTC")
    assert pos.size == 2.0
    assert pos.entry_price == pytest.approx(110_000.0)


def test_realized_pnl_on_close(broker):
    broker.place_order(Order("BTC", Side.LONG, 1.0))  # @100k
    broker.price_source.set_price("BTC", 110_000.0)
    broker.place_order(Order("BTC", Side.SHORT, 1.0))  # close @110k -> +10k
    assert broker.realized_pnl == pytest.approx(10_000.0)
    assert broker.get_account().position_for("BTC") is None


def test_flip_long_to_short(broker):
    broker.place_order(Order("BTC", Side.LONG, 1.0))  # @100k
    broker.price_source.set_price("BTC", 100_000.0)
    broker.place_order(Order("BTC", Side.SHORT, 3.0))  # close 1 + open 2 short
    pos = broker.get_account().position_for("BTC")
    assert pos.side is Side.SHORT
    assert pos.size == pytest.approx(2.0)


def test_reduce_only_caps_at_position_size(broker):
    broker.place_order(Order("BTC", Side.LONG, 1.0))
    res = broker.place_order(Order("BTC", Side.SHORT, 5.0, reduce_only=True))
    assert res.filled_size == pytest.approx(1.0)  # capped to existing size
    assert broker.get_account().position_for("BTC") is None


def test_reduce_only_without_position_rejected(broker):
    res = broker.place_order(Order("ETH", Side.SHORT, 1.0, reduce_only=True))
    assert res.status is OrderStatus.REJECTED


def test_no_price_rejects():
    src = StaticPriceSource("paper", {}, spread_bps=0.0)
    b = PaperBroker("paper", src)
    res = b.place_order(Order("DOGE", Side.LONG, 1.0))
    assert res.status is OrderStatus.REJECTED


def test_close_position_helper(broker):
    broker.place_order(Order("ETH", Side.LONG, 2.0))
    res = broker.close_position("ETH")
    assert res.status is OrderStatus.FILLED
    assert broker.get_account().position_for("ETH") is None


def test_non_marketable_limit_rests(broker):
    # spread is 0, so ask == bid == 100k. A buy limit below the ask can't fill.
    res = broker.place_order(
        Order("BTC", Side.LONG, 1.0, order_type=OrderType.LIMIT, limit_price=99_000)
    )
    assert res.status is OrderStatus.PENDING
    assert res.filled_size == 0.0
    assert broker.get_account().position_for("BTC") is None


def test_marketable_limit_fills(broker):
    res = broker.place_order(
        Order("BTC", Side.LONG, 1.0, order_type=OrderType.LIMIT, limit_price=100_000)
    )
    assert res.status is OrderStatus.FILLED
    assert broker.get_account().position_for("BTC").size == 1.0
