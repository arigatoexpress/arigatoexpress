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
