"""Unit tests for signal consumer settings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from signal_consumer import config as config_module
from signal_consumer.config import Settings


def test_edge_threshold_pct_accepts_bounds():
    settings_min = Settings(edge_threshold_pct=0.0)
    settings_max = Settings(edge_threshold_pct=100.0)

    assert settings_min.edge_threshold_pct == 0.0
    assert settings_max.edge_threshold_pct == 100.0


@pytest.mark.parametrize("value", [-0.0001, 100.0001])
def test_edge_threshold_pct_rejects_out_of_bounds(value: float):
    with pytest.raises(ValidationError):
        Settings(edge_threshold_pct=value)


def test_get_settings_is_cached(monkeypatch):
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("ENV", "prod")

    s1 = config_module.get_settings()
    monkeypatch.setenv("ENV", "dev")
    s2 = config_module.get_settings()

    assert s1 is s2
    assert s2.env == "prod"
    config_module.get_settings.cache_clear()
