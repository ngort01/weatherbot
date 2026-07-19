"""Characterization tests for forecast helpers (pure / no network)."""
from datetime import datetime, timezone

from weatherbet.forecasts import (
    OPEN_METEO_SOURCES,
    _hrrr_horizon_date,
    _parse_daily_maxes,
    c_to_display,
    forecast_panel,
    open_meteo_params,
    persistable_forecast_snap,
    pick_best,
    sources_for_region,
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


def test_pick_best_ignores_regional_sources_for_trading():
    """Extra models are stored but not selected until blending ships."""
    snap = {
        "hrrr": None,
        "ecmwf": 22.0,
        "icon": 24.0,
        "meteofrance": 23.5,
        "ukmo": 21.0,
    }
    assert pick_best(snap, "eu") == (22.0, "ecmwf")


def test_forecast_panel_us_spread():
    """PR4: multi-source temps + max−min spread on signal annotations."""
    panel = forecast_panel({
        "ts": "2026-07-19T12:00:00+00:00",
        "ecmwf": 79,
        "hrrr": 87,
        "metar": None,
        "best": 87,
        "best_source": "hrrr",
    })
    assert panel == {"ecmwf": 79, "hrrr": 87, "spread": 8.0}
    # Meta / pick keys never leak into the panel
    assert "best" not in panel
    assert "best_source" not in panel
    assert "ts" not in panel


def test_forecast_panel_skips_nulls_and_missing():
    assert forecast_panel(None) is None
    assert forecast_panel({}) is None
    assert forecast_panel({"ecmwf": None, "hrrr": None, "best": 80}) is None
    # Single source → spread 0
    assert forecast_panel({"ecmwf": 22.0, "icon": None}) == {
        "ecmwf": 22.0, "spread": 0.0,
    }


def test_forecast_panel_regional_models_ordered():
    panel = forecast_panel({
        "ecmwf": 22.0,
        "icon": 24.0,
        "meteofrance": 23.5,
        "ukmo": 21.0,
        "metar": 20.0,
        "best": 22.0,
        "best_source": "ecmwf",
    })
    assert panel["spread"] == 4.0  # 24.0 − 20.0
    assert list(panel.keys()) == [
        "ecmwf", "icon", "meteofrance", "ukmo", "metar", "spread",
    ]


def test_sources_for_region_assignment():
    assert sources_for_region("us") == ["ecmwf", "hrrr"]
    assert sources_for_region("eu") == ["ecmwf", "icon", "meteofrance", "ukmo"]
    assert sources_for_region("ca") == ["ecmwf", "gem"]
    assert sources_for_region("asia") == ["ecmwf", "jma", "kma", "cma"]
    assert sources_for_region("oc") == ["ecmwf", "bom"]
    assert sources_for_region("sa") == ["ecmwf"]


def test_open_meteo_registry_has_models():
    for key, cfg in OPEN_METEO_SOURCES.items():
        assert cfg.get("model"), key
        assert cfg.get("tag"), key


def test_persistable_forecast_snap_keeps_regional_sources():
    snap = {
        "ts": "2026-07-18T12:00:00+00:00",
        "ecmwf": 22.0,
        "icon": 23.1,
        "meteofrance": 22.5,
        "ukmo": 21.8,
        "metar": 20.0,
        "best": 22.0,
        "best_source": "ecmwf",
    }
    out = persistable_forecast_snap(snap, "D+0", 12.34)
    assert out["horizon"] == "D+0"
    assert out["hours_left"] == 12.3
    assert out["icon"] == 23.1
    assert out["meteofrance"] == 22.5
    assert out["ukmo"] == 21.8
    assert out["ecmwf"] == 22.0
    assert out["best_source"] == "ecmwf"
    # US-only key not on snap → omitted (not forced to None)
    assert "hrrr" not in out
    assert "gem" not in out


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
