import pytest

from sapphire_perps.config import RiskLimits
from sapphire_perps.risk.kernel import RiskKernel
from sapphire_perps.types import AccountState, Order, Position, Side


@pytest.fixture
def limits():
    return RiskLimits(
        max_order_notional_usd=10_000,
        min_order_notional_usd=100,
        max_position_notional_usd=20_000,
        max_total_notional_usd=50_000,
        max_leverage=10,
        max_open_positions=2,
        daily_loss_limit_usd=1_000,
        allowed_symbols=["BTC", "ETH"],
    )


@pytest.fixture
def kernel(limits):
    return RiskKernel(limits)


def empty_account():
    return AccountState(venue="paper", equity=100_000, free_collateral=100_000, positions=[])


def test_approves_within_limits(kernel):
    # 0.05 BTC * $100k = $5,000 -> within $10k max order -> approve
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.05), 100_000, empty_account())
    assert d.approved is True


def test_rejects_no_price(kernel):
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.05), 0, empty_account())
    assert not d.approved
    assert any("mark price" in r for r in d.reasons)


def test_rejects_no_account(kernel):
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.05), 100_000, None)
    assert not d.approved


def test_rejects_symbol_not_allowed(kernel):
    d = kernel.evaluate(Order("DOGE", Side.LONG, 1.0), 1.0, empty_account())
    assert not d.approved
    assert any("allowlist" in r for r in d.reasons)


def test_rejects_oversize_order(kernel):
    d = kernel.evaluate(Order("BTC", Side.LONG, 1.0), 100_000, empty_account())  # $100k
    assert not d.approved
    assert any("exceeds max" in r for r in d.reasons)


def test_rejects_below_min(kernel):
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.0001), 100_000, empty_account())  # $10
    assert not d.approved
    assert any("below min" in r for r in d.reasons)


def test_rejects_excess_leverage(kernel):
    o = Order("BTC", Side.LONG, 0.05, leverage=25)
    d = kernel.evaluate(o, 100_000, empty_account())
    assert not d.approved
    assert any("leverage" in r for r in d.reasons)


def test_enforces_leverage_without_explicit_field(kernel):
    # $5k order within notional caps, but only $100 equity -> 50x >> 10x cap.
    acct = AccountState(venue="paper", equity=100, free_collateral=100, positions=[])
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.05), 100_000, acct)  # no leverage set
    assert not d.approved
    assert any("effective leverage" in r for r in d.reasons)


def test_rejects_non_positive_equity(kernel):
    acct = AccountState(venue="paper", equity=0, free_collateral=0, positions=[])
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.001), 100_000, acct)
    assert not d.approved
    assert any("equity" in r for r in d.reasons)


def test_resulting_position_cap(kernel):
    acct = AccountState(
        venue="paper", equity=100_000, free_collateral=100_000,
        positions=[Position("BTC", "paper", Side.LONG, 0.18, 100_000, 100_000)],  # $18k
    )
    # add another $5k -> $23k > $20k cap
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.05), 100_000, acct)
    assert not d.approved
    assert any("position" in r for r in d.reasons)


def test_max_open_positions(kernel):
    acct = AccountState(
        venue="paper", equity=100_000, free_collateral=100_000,
        positions=[
            Position("BTC", "paper", Side.LONG, 0.05, 100_000, 100_000),
            Position("ETH", "paper", Side.LONG, 1.0, 3_000, 3_000),
        ],
    )
    # opening a 3rd symbol — but only BTC/ETH allowed, so use a fresh allowed one
    # Both allowed symbols already open; a new order on a non-open allowed symbol
    # is impossible here, so assert the count guard via reduce of an existing one.
    # Instead: confirm count guard triggers when both slots full and we try ETH? ETH already open -> not new.
    # Use limits with SOL allowed to make a true 3rd.
    acct.positions.append(Position("SOL", "paper", Side.LONG, 1.0, 180, 180))
    kernel.limits.allowed_symbols.append("SOL")
    kernel.limits.allowed_symbols.append("XRP")
    d = kernel.evaluate(Order("XRP", Side.LONG, 100, ), 1.0, acct)
    assert not d.approved
    assert any("max open positions" in r for r in d.reasons)


def test_daily_loss_breaker_blocks_new_but_allows_reduce(kernel):
    acct = AccountState(
        venue="paper", equity=100_000, free_collateral=100_000,
        positions=[Position("BTC", "paper", Side.LONG, 0.05, 100_000, 100_000)],
    )
    new = kernel.evaluate(Order("ETH", Side.LONG, 1.0), 3_000, acct, daily_pnl=-1_500)
    assert not new.approved
    assert any("daily loss" in r for r in new.reasons)

    reduce = kernel.evaluate(
        Order("BTC", Side.SHORT, 0.05, reduce_only=True), 100_000, acct, daily_pnl=-1_500
    )
    assert reduce.approved is True


def test_reduce_only_without_position_rejected(kernel):
    d = kernel.evaluate(
        Order("BTC", Side.SHORT, 0.05, reduce_only=True), 100_000, empty_account()
    )
    assert not d.approved
    assert any("no open position to reduce" in r for r in d.reasons)


def test_reduce_only_same_side_rejected(kernel):
    # reduce_only LONG against an existing LONG would *increase* exposure.
    acct = AccountState(
        venue="paper", equity=100_000, free_collateral=100_000,
        positions=[Position("BTC", "paper", Side.LONG, 0.05, 100_000, 100_000)],
    )
    d = kernel.evaluate(Order("BTC", Side.LONG, 0.05, reduce_only=True), 100_000, acct)
    assert not d.approved
    assert any("same side" in r for r in d.reasons)
