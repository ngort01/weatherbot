"""
Shared fixtures for WeatherBet characterization tests.

Tests pin *current* behavior. See TESTING_PLAN.md.
Run from repo root: pytest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Repo root (parent of tests/)
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return ROOT


@pytest.fixture
def cfg() -> dict:
    """Committed config.json defaults used by the bot at import time."""
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


@pytest.fixture
def wb(monkeypatch, tmp_path):
    """
    Import weatherbet with data/calibration paths redirected to tmp_path
    so tests never touch real paper-trading state.

    Paths and risk limits live in weatherbet.config; the package re-exports
    them. Patch both so functions (config.X) and tests (wb.X) stay in sync.
    """
    import weatherbet as mod
    from weatherbet import config
    from weatherbet import calibration

    data = tmp_path / "data"
    markets = data / "markets"
    markets.mkdir(parents=True)
    cal = data / "calibration.json"
    state = data / "state.json"

    for name, val in [
        ("DATA_DIR", data),
        ("MARKETS_DIR", markets),
        ("CALIBRATION_FILE", cal),
        ("STATE_FILE", state),
    ]:
        monkeypatch.setattr(config, name, val)
        monkeypatch.setattr(mod, name, val)

    empty_cal = {}
    monkeypatch.setattr(calibration, "_cal", empty_cal)
    monkeypatch.setattr(mod, "_cal", empty_cal)

    return mod


@pytest.fixture
def patch_config(monkeypatch, wb):
    """
    Helper fixture: return a callable to patch a config constant on both
    weatherbet.config and the package namespace (for risk/entry tests).
    """
    from weatherbet import config

    def _patch(name, value):
        monkeypatch.setattr(config, name, value)
        monkeypatch.setattr(wb, name, value)

    return _patch
