from sapphire_perps.cli import build_parser


def test_venue_accepted_after_subcommand():
    # The docstring advertises `trade BTC long 0.01 --venue hyperliquid`.
    parser = build_parser()
    args = parser.parse_args(["trade", "BTC", "long", "0.01", "--venue", "hyperliquid"])
    assert args.command == "trade"
    assert args.venue == "hyperliquid"
    assert args.size == 0.01


def test_venue_after_quote_and_positions():
    parser = build_parser()
    assert parser.parse_args(["quote", "BTC", "--venue", "lighter"]).venue == "lighter"
    assert parser.parse_args(["positions", "--venue", "lighter"]).venue == "lighter"


def test_venue_defaults_none():
    parser = build_parser()
    assert parser.parse_args(["positions"]).venue is None
