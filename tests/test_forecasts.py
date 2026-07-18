"""Characterization tests for forecast helpers (pure / no network)."""
from datetime import datetime, timezone

from weatherbet.forecasts import (
    _hrrr_horizon_date,
    _parse_daily_maxes,
    c_to_display,
    open_meteo_params,
    pick_best,
)


def test_parse_daily_maxes_filters_dates_and_nones():
    data = {
        "daily": {
            "time": ["2026-07-18", "2026-07-19", "2026-07-20"],
            "temperature_2m_max": [80.4, None, 88.0],
        }
    }
    out = _parse_daily_maxes(data, {"2026-07-18", "2026-07-20"}, round)
    assert out == {"2026-07-18": 80, "2026-07-20": 88}


def test_parse_daily_maxes_error_or_empty():
    assert _parse_daily_maxes(None, {"2026-07-18"}, round) == {}
    assert _parse_daily_maxes({"error": True}, {"2026-07-18"}, round) == {}
    assert _parse_daily_maxes({"daily": {}}, {"2026-07-18"}, round) == {}


def test_parse_daily_maxes_celsius_rounding():
    data = {
        "daily": {
            "time": ["2026-07-18"],
            "temperature_2m_max": [21.46],
        }
    }
    out = _parse_daily_maxes(data, {"2026-07-18"}, lambda t: round(t, 1))
    assert out == {"2026-07-18": 21.5}


def test_pick_best_us_prefers_hrrr():
    assert pick_best({"hrrr": 90, "ecmwf": 88}, "us") == (90, "hrrr")
    assert pick_best({"hrrr": None, "ecmwf": 88}, "us") == (88, "ecmwf")
    assert pick_best({"hrrr": None, "ecmwf": None}, "us") == (None, None)


def test_pick_best_non_us_ignores_hrrr():
    assert pick_best({"hrrr": 90, "ecmwf": 88}, "eu") == (88, "ecmwf")
    assert pick_best({"hrrr": 90, "ecmwf": None}, "eu") == (None, None)


def test_c_to_display():
    assert c_to_display(0, "F") == 32
    assert c_to_display(20, "F") == 68
    assert c_to_display(20.44, "C") == 20.4


def test_hrrr_horizon_date():
    now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    assert _hrrr_horizon_date(now) == "2026-07-20"


def test_open_meteo_params_bias_correction():
    loc = {"lat": 40.0, "lon": -74.0}
    p = open_meteo_params(
        loc, "nyc",
        model="ecmwf_ifs025",
        temp_unit="fahrenheit",
        forecast_days=7,
        bias_correction=True,
    )
    assert p["bias_correction"] == "true"
    assert p["models"] == "ecmwf_ifs025"
    assert p["latitude"] == 40.0

    p2 = open_meteo_params(
        loc, "nyc",
        model="gfs_seamless",
        temp_unit="fahrenheit",
        forecast_days=3,
    )
    assert "bias_correction" not in p2
