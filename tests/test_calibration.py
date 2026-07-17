"""
Calibration + snapshot temp extraction after IMPROVEMENTS §2 wiring.
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


def test_snapshot_source_temp_production_shape():
    snap = {"ecmwf": 82, "hrrr": 81, "metar": 80, "best": 81, "best_source": "hrrr"}
    assert wb.snapshot_source_temp(snap, "ecmwf") == 82
    assert wb.snapshot_source_temp(snap, "hrrr") == 81
    assert wb.snapshot_source_temp(snap, "metar") == 80
    assert wb.snapshot_source_temp(snap, "gfs") is None


def test_snapshot_source_temp_legacy_shape():
    snap = {"source": "ecmwf", "temp": 79}
    assert wb.snapshot_source_temp(snap, "ecmwf") == 79
    assert wb.snapshot_source_temp(snap, "hrrr") is None


def _fake_resolved_legacy(city, actual, source, temp):
    return {
        "city": city,
        "resolved": True,
        "status": "resolved",
        "actual_temp": actual,
        "forecast_snapshots": [{"source": source, "temp": temp}],
    }


def _fake_resolved_production(city, actual, ecmwf=None, hrrr=None):
    return {
        "city": city,
        "status": "resolved",
        "resolved": True,
        "actual_temp": actual,
        "forecast_snapshots": [{
            "ts": "2026-07-16T00:00:00+00:00",
            "ecmwf": ecmwf,
            "hrrr": hrrr,
            "metar": None,
            "best": hrrr if hrrr is not None else ecmwf,
            "best_source": "hrrr" if hrrr is not None else "ecmwf",
        }],
    }


def test_run_calibration_skips_below_min(wb, patch_config):
    patch_config("CALIBRATION_MIN", 30)
    markets = [_fake_resolved_legacy("nyc", 80, "ecmwf", 82) for _ in range(10)]
    cal = wb.run_calibration(markets)
    assert "nyc_ecmwf" not in cal


def test_run_calibration_updates_legacy_shape(wb, patch_config):
    patch_config("CALIBRATION_MIN", 5)
    markets = [_fake_resolved_legacy("nyc", 80, "ecmwf", 82) for _ in range(5)]
    cal = wb.run_calibration(markets)
    assert cal["nyc_ecmwf"]["sigma"] == 2.0
    assert cal["nyc_ecmwf"]["n"] == 5
    assert cal["nyc_ecmwf"]["bias"] == 2.0  # forecast - actual


def test_run_calibration_production_snapshot_shape(wb, patch_config):
    patch_config("CALIBRATION_MIN", 3)
    markets = [
        _fake_resolved_production("nyc", 80, ecmwf=82, hrrr=81) for _ in range(3)
    ]
    cal = wb.run_calibration(markets)
    assert cal["nyc_ecmwf"]["sigma"] == 2.0
    assert cal["nyc_hrrr"]["sigma"] == 1.0
    assert cal["nyc_ecmwf"]["bias"] == 2.0
    assert cal["nyc_hrrr"]["bias"] == 1.0


def test_run_calibration_accepts_status_resolved(wb, patch_config):
    """status=='resolved' is enough (no separate resolved flag required)."""
    patch_config("CALIBRATION_MIN", 2)
    markets = [{
        "city": "nyc",
        "status": "resolved",
        "actual_temp": 80,
        "forecast_snapshots": [{"ecmwf": 81, "hrrr": None, "metar": None}],
    } for _ in range(2)]
    cal = wb.run_calibration(markets)
    assert cal["nyc_ecmwf"]["sigma"] == 1.0


def test_run_calibration_requires_actual_temp(wb, patch_config):
    patch_config("CALIBRATION_MIN", 1)
    markets = [{
        "city": "nyc",
        "status": "resolved",
        "resolved": True,
        "actual_temp": None,
        "forecast_snapshots": [{"ecmwf": 80}],
    }]
    cal = wb.run_calibration(markets)
    assert "nyc_ecmwf" not in cal
