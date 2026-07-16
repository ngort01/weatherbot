"""
Characterization: get_sigma, load_cal, run_calibration.

Documents current quirks:
- run_calibration filters on m["resolved"] (truthy), not status=="resolved"
- It expects forecast_snapshots entries with keys source + temp
  (production snapshots use ecmwf/hrrr/best/best_source — different shape)
"""

import json

import weatherbet as wb


def test_get_sigma_defaults_f_and_c(wb):
    assert wb.get_sigma("nyc", "ecmwf") == wb.SIGMA_F == 2.0
    assert wb.get_sigma("london", "ecmwf") == wb.SIGMA_C == 1.2


def test_get_sigma_from_cal_cache(wb):
    wb._cal["nyc_hrrr"] = {"sigma": 1.25, "n": 40}
    assert wb.get_sigma("nyc", "hrrr") == 1.25


def test_load_cal_missing_file(wb):
    assert wb.load_cal() == {}


def test_load_cal_reads_json(wb):
    payload = {"nyc_ecmwf": {"sigma": 1.5, "n": 30}}
    wb.CALIBRATION_FILE.write_text(json.dumps(payload), encoding="utf-8")
    assert wb.load_cal() == payload


def _fake_resolved(city, actual, source, temp, n_extra=0):
    """Shape that run_calibration *expects* (not production snapshot shape)."""
    snaps = [{"source": source, "temp": temp} for _ in range(1 + n_extra)]
    return {
        "city": city,
        "resolved": True,
        "actual_temp": actual,
        "forecast_snapshots": snaps,
    }


def test_run_calibration_skips_below_min(wb, monkeypatch):
    monkeypatch.setattr(wb, "CALIBRATION_MIN", 30)
    markets = [_fake_resolved("nyc", 80, "ecmwf", 82) for _ in range(10)]
    cal = wb.run_calibration(markets)
    assert "nyc_ecmwf" not in cal
    # File still written (possibly empty/prior)
    assert wb.CALIBRATION_FILE.exists()


def test_run_calibration_updates_when_enough_errors(wb, monkeypatch):
    monkeypatch.setattr(wb, "CALIBRATION_MIN", 5)
    # MAE = |82-80| = 2.0 for each
    markets = [_fake_resolved("nyc", 80, "ecmwf", 82) for _ in range(5)]
    cal = wb.run_calibration(markets)
    assert cal["nyc_ecmwf"]["sigma"] == 2.0
    assert cal["nyc_ecmwf"]["n"] == 5
    disk = json.loads(wb.CALIBRATION_FILE.read_text(encoding="utf-8"))
    assert disk["nyc_ecmwf"]["sigma"] == 2.0


def test_run_calibration_ignores_status_resolved_without_resolved_flag(wb, monkeypatch):
    """Production resolve sets status='resolved' but not necessarily resolved=True."""
    monkeypatch.setattr(wb, "CALIBRATION_MIN", 1)
    markets = [{
        "city": "nyc",
        "status": "resolved",
        "resolved": None,  # or missing
        "actual_temp": 80,
        "forecast_snapshots": [{"source": "ecmwf", "temp": 81}],
    }]
    # m.get("resolved") is falsy → skipped
    cal = wb.run_calibration(markets)
    assert "nyc_ecmwf" not in cal


def test_run_calibration_crashes_on_production_snapshot_shape(wb, monkeypatch):
    """
    Production snaps use ecmwf/hrrr/best keys, not source/temp.
    Current run_calibration does s["source"] and raises KeyError — dead path.
    """
    import pytest

    monkeypatch.setattr(wb, "CALIBRATION_MIN", 1)
    markets = [{
        "city": "nyc",
        "resolved": True,
        "actual_temp": 80,
        "forecast_snapshots": [{
            "ts": "2026-07-16T00:00:00+00:00",
            "ecmwf": 82,
            "hrrr": 81,
            "best": 81,
            "best_source": "hrrr",
        }],
    }]
    with pytest.raises(KeyError, match="source"):
        wb.run_calibration(markets)


def test_run_calibration_requires_actual_temp(wb, monkeypatch):
    monkeypatch.setattr(wb, "CALIBRATION_MIN", 1)
    markets = [{
        "city": "nyc",
        "resolved": True,
        "actual_temp": None,
        "forecast_snapshots": [{"source": "ecmwf", "temp": 80}],
    }]
    cal = wb.run_calibration(markets)
    assert "nyc_ecmwf" not in cal
