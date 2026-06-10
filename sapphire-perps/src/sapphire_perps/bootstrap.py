"""Wiring helpers: build adapters, router, and engine from an AppConfig."""

from __future__ import annotations

import logging

from .config import AppConfig
from .engine import Engine
from .execution.approval import ApprovalGate, AutoDenyGate, CLIApprovalGate
from .execution.router import OrderRouter
from .risk.kernel import RiskKernel
from .signals.base import Signal
from .signals.momentum import MomentumSignal
from .venues import build_adapter
from .venues.base import VenueAdapter


def build_adapters(config: AppConfig) -> dict[str, VenueAdapter]:
    adapters: dict[str, VenueAdapter] = {}
    for name in config.enabled_venues():
        try:
            adapters[name] = build_adapter(name, config)
        except NotImplementedError as exc:
            logging.getLogger("sapphire_perps").warning(
                "venue %s unavailable: %s", name, exc
            )
    return adapters


def build_router(
    config: AppConfig,
    approval: ApprovalGate | None = None,
    adapters: dict[str, VenueAdapter] | None = None,
) -> OrderRouter:
    adapters = adapters if adapters is not None else build_adapters(config)
    risk = RiskKernel(config.risk)
    # Default approval gate: interactive in live, deny otherwise.
    if approval is None:
        approval = CLIApprovalGate() if config.is_live else AutoDenyGate()
    return OrderRouter(
        venues=adapters, risk=risk, config=config, approval=approval
    )


def build_engine(
    config: AppConfig,
    signal: Signal | None = None,
    approval: ApprovalGate | None = None,
) -> Engine:
    router = build_router(config, approval=approval)
    signal = signal or MomentumSignal()
    return Engine(config=config, router=router, signal=signal)
