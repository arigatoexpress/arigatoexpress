"""Configuration loading.

Config is layered, lowest -> highest precedence:
  1. Built-in dataclass defaults (paper, fail-closed).
  2. A YAML/JSON config file (``config/default.yaml`` by default).
  3. Environment variables (``SAPPHIRE_*``).

Secrets (venue API keys / wallet keys) are NEVER read from the config file —
only from the environment — so they can't be committed by accident.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, replace
from typing import Any

from .types import ExecMode

ENV_PREFIX = "SAPPHIRE_"


@dataclass
class RiskLimits:
    """Hard pre-trade limits. Any breach => order rejected (fail closed)."""

    max_order_notional_usd: float = 5_000.0
    min_order_notional_usd: float = 10.0
    max_position_notional_usd: float = 25_000.0
    max_total_notional_usd: float = 100_000.0
    max_leverage: float = 10.0
    max_open_positions: int = 5
    daily_loss_limit_usd: float = 2_000.0
    allowed_symbols: list[str] = field(
        default_factory=lambda: ["BTC", "ETH", "SOL"]
    )


@dataclass
class VenueConfig:
    name: str
    enabled: bool = True
    testnet: bool = True


def _default_venues() -> dict[str, VenueConfig]:
    return {
        "hyperliquid": VenueConfig(name="hyperliquid", enabled=True, testnet=True),
        "lighter": VenueConfig(name="lighter", enabled=False, testnet=True),
        "robinhood": VenueConfig(name="robinhood", enabled=False, testnet=True),
    }


@dataclass
class AppConfig:
    exec_mode: ExecMode = ExecMode.PAPER
    # Live execution is double-gated: exec_mode must be LIVE *and* allow_live True.
    allow_live: bool = False
    base_currency: str = "USD"
    default_venue: str = "hyperliquid"
    poll_interval_s: float = 15.0
    paper_starting_equity_usd: float = 100_000.0
    paper_slippage_bps: float = 2.0
    risk: RiskLimits = field(default_factory=RiskLimits)
    venues: dict[str, VenueConfig] = field(default_factory=_default_venues)

    # ---- derived helpers -------------------------------------------------
    @property
    def is_live(self) -> bool:
        """True only when the system is *fully* cleared for real orders."""
        return self.exec_mode is ExecMode.LIVE and self.allow_live

    def enabled_venues(self) -> list[str]:
        return [name for name, v in self.venues.items() if v.enabled]

    def venue(self, name: str) -> VenueConfig:
        if name not in self.venues:
            raise KeyError(f"unknown venue: {name!r}")
        return self.venues[name]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _read_config_file(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "PyYAML is required to read YAML config; "
                "`pip install pyyaml` or use a .json config"
            ) from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text) if text.strip() else {}
    if not isinstance(data, dict):
        raise ValueError(f"config file {path!r} must contain a mapping at the top level")
    return data


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _apply_mapping(cfg: AppConfig, data: dict[str, Any]) -> AppConfig:
    updates: dict[str, Any] = {}
    for key, value in data.items():
        if key == "risk" and isinstance(value, dict):
            updates["risk"] = replace(cfg.risk, **_filter_fields(RiskLimits, value))
        elif key == "venues" and isinstance(value, dict):
            venues = dict(cfg.venues)
            for vname, vdata in value.items():
                vdata = vdata or {}
                venues[vname] = VenueConfig(
                    name=vname,
                    enabled=_coerce_bool(vdata.get("enabled", True)),
                    testnet=_coerce_bool(vdata.get("testnet", True)),
                )
            updates["venues"] = venues
        elif key == "exec_mode":
            updates["exec_mode"] = ExecMode(str(value).lower())
        elif key == "allow_live":
            updates["allow_live"] = _coerce_bool(value)
        elif key in {f.name for f in fields(AppConfig)}:
            updates[key] = value
    return replace(cfg, **updates)


def _filter_fields(cls: Any, data: dict[str, Any]) -> dict[str, Any]:
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


def _apply_env(cfg: AppConfig) -> AppConfig:
    updates: dict[str, Any] = {}
    if (v := os.getenv(f"{ENV_PREFIX}EXEC_MODE")):
        updates["exec_mode"] = ExecMode(v.lower())
    if (v := os.getenv(f"{ENV_PREFIX}ALLOW_LIVE")) is not None:
        updates["allow_live"] = _coerce_bool(v)
    if (v := os.getenv(f"{ENV_PREFIX}DEFAULT_VENUE")):
        updates["default_venue"] = v
    if (v := os.getenv(f"{ENV_PREFIX}POLL_INTERVAL_S")):
        updates["poll_interval_s"] = float(v)
    return replace(cfg, **updates) if updates else cfg


def load_config(path: str | None = None) -> AppConfig:
    """Build the effective config. ``path`` is optional; if it points at a
    missing file we fall back to defaults (still valid, paper-mode)."""
    cfg = AppConfig()
    if path and os.path.exists(path):
        cfg = _apply_mapping(cfg, _read_config_file(path))
    cfg = _apply_env(cfg)
    _validate(cfg)
    return cfg


def _validate(cfg: AppConfig) -> None:
    r = cfg.risk
    if r.min_order_notional_usd <= 0:
        raise ValueError("risk.min_order_notional_usd must be > 0")
    if r.max_order_notional_usd < r.min_order_notional_usd:
        raise ValueError("max_order_notional must be >= min_order_notional")
    if r.max_position_notional_usd < r.max_order_notional_usd:
        raise ValueError("max_position_notional must be >= max_order_notional")
    if r.max_total_notional_usd < r.max_position_notional_usd:
        raise ValueError("max_total_notional must be >= max_position_notional")
    if r.max_leverage <= 0:
        raise ValueError("max_leverage must be > 0")
    if cfg.exec_mode is ExecMode.LIVE and not cfg.allow_live:
        # Not an error — this is the fail-closed posture. We simply log intent
        # via the derived `is_live` flag remaining False. Callers must check it.
        pass
