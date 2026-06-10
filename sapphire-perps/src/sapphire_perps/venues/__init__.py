"""Venue adapters: a uniform interface over heterogeneous perp exchanges."""

from .base import PriceSource, StaticPriceSource, VenueAdapter
from .paper import PaperBroker

__all__ = ["VenueAdapter", "PriceSource", "StaticPriceSource", "PaperBroker"]


def build_adapter(name: str, config) -> VenueAdapter:
    """Factory: construct the right adapter for ``name`` given app config.

    Imports are local so that, e.g., loading the Hyperliquid adapter never
    drags in the Lighter SDK and vice-versa.
    """
    name = name.lower()
    if name == "hyperliquid":
        from .hyperliquid import HyperliquidAdapter

        return HyperliquidAdapter(config)
    if name == "lighter":
        from .lighter import LighterAdapter

        return LighterAdapter(config)
    if name == "robinhood":
        from .robinhood import RobinhoodAdapter

        return RobinhoodAdapter(config)
    raise KeyError(f"no adapter registered for venue {name!r}")
