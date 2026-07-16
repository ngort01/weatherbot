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
    """
    import weatherbet as mod

    data = tmp_path / "data"
    markets = data / "markets"
    markets.mkdir(parents=True)
    cal = data / "calibration.json"
    state = data / "state.json"

    monkeypatch.setattr(mod, "DATA_DIR", data)
    monkeypatch.setattr(mod, "MARKETS_DIR", markets)
    monkeypatch.setattr(mod, "CALIBRATION_FILE", cal)
    monkeypatch.setattr(mod, "STATE_FILE", state)
    monkeypatch.setattr(mod, "_cal", {})

    return mod
