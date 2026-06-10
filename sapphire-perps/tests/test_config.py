import json

import pytest

from sapphire_perps.config import AppConfig, load_config
from sapphire_perps.types import ExecMode


def test_defaults_are_paper_and_failclosed():
    cfg = AppConfig()
    assert cfg.exec_mode is ExecMode.PAPER
    assert cfg.allow_live is False
    assert cfg.is_live is False


def test_live_requires_both_flags():
    cfg = AppConfig(exec_mode=ExecMode.LIVE, allow_live=False)
    assert cfg.is_live is False  # fail closed
    cfg = AppConfig(exec_mode=ExecMode.LIVE, allow_live=True)
    assert cfg.is_live is True


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("SAPPHIRE_EXEC_MODE", "live")
    monkeypatch.setenv("SAPPHIRE_ALLOW_LIVE", "true")
    cfg = load_config(str(tmp_path / "does-not-exist.yaml"))
    assert cfg.is_live is True


def test_json_config_file(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({
        "default_venue": "lighter",
        "risk": {"max_leverage": 3, "allowed_symbols": ["BTC"]},
        "venues": {"lighter": {"enabled": True, "testnet": True}},
    }))
    cfg = load_config(str(path))
    assert cfg.default_venue == "lighter"
    assert cfg.risk.max_leverage == 3
    assert cfg.risk.allowed_symbols == ["BTC"]
    assert "lighter" in cfg.enabled_venues()


def test_validation_rejects_inverted_limits():
    with pytest.raises(ValueError):
        from sapphire_perps.config import RiskLimits, _validate
        bad = AppConfig(risk=RiskLimits(max_order_notional_usd=10, min_order_notional_usd=100))
        _validate(bad)
