from sapphire_perps.venues.hyperliquid import HyperliquidAdapter


def test_round_px_caps_significant_figures():
    r = HyperliquidAdapter._round_px
    # 5 significant figures
    assert r(96000.0 * 1.01) == 96960.0      # 96960 -> 5 sig figs, integer
    assert r(3400.0 * 0.99) == 3366.0
    # sub-dollar prices keep precision within 6 decimals
    assert r(0.9 * 1.01) == 0.909
    # already-clean integers pass through
    assert r(100000.0) == 100000.0


def test_round_px_non_positive_passthrough():
    assert HyperliquidAdapter._round_px(0.0) == 0.0
    assert HyperliquidAdapter._round_px(-5.0) == -5.0


def test_round_size_truncates_to_lot_precision():
    r = HyperliquidAdapter._round_size
    # szDecimals=3 -> truncate (floor), never round up
    assert r(0.123456, 3) == 0.123
    assert r(0.1239, 3) == 0.123
    # szDecimals=0 -> whole units only
    assert r(2.9, 0) == 2.0
    # sizes below one lot floor to 0 (caller rejects)
    assert r(0.0004, 3) == 0.0
