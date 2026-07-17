"""Forecast residual calibration (sigma / bias)."""
import json
from datetime import datetime, timezone

from weatherbet import config

_cal: dict = {}


def load_cal():
    if config.CALIBRATION_FILE.exists():
        return json.loads(config.CALIBRATION_FILE.read_text(encoding="utf-8"))
    return {}

def get_sigma(city_slug, source="ecmwf"):
    key = f"{city_slug}_{source}"
    if key in _cal:
        return _cal[key]["sigma"]
    return config.SIGMA_F if config.LOCATIONS[city_slug]["unit"] == "F" else config.SIGMA_C

def snapshot_source_temp(snap, source):
    """
    Extract a source temperature from a forecast snapshot.
    Supports production shape (ecmwf/hrrr/metar keys) and legacy
    characterization shape ({"source": "...", "temp": ...}).
    """
    if not snap:
        return None
    if source in snap and snap[source] is not None:
        return snap[source]
    if snap.get("source") == source and snap.get("temp") is not None:
        return snap["temp"]
    return None

def run_calibration(markets):
    """Recalculates sigma (MAE) and bias (mean signed error) from markets with actuals."""
    resolved = [
        m for m in markets
        if m.get("actual_temp") is not None
        and (m.get("status") == "resolved" or m.get("resolved"))
    ]
    cal = load_cal()
    updated = []

    for source in ["ecmwf", "hrrr", "metar"]:
        for city in set(m["city"] for m in resolved):
            group = [m for m in resolved if m["city"] == city]
            abs_errors = []
            signed_errors = []
            for m in group:
                temp = None
                for s in reversed(m.get("forecast_snapshots", [])):
                    temp = snapshot_source_temp(s, source)
                    if temp is not None:
                        break
                if temp is not None:
                    err = float(temp) - float(m["actual_temp"])
                    signed_errors.append(err)
                    abs_errors.append(abs(err))
            if len(abs_errors) < config.CALIBRATION_MIN:
                continue
            mae = sum(abs_errors) / len(abs_errors)
            bias = sum(signed_errors) / len(signed_errors)
            key = f"{city}_{source}"
            old = cal.get(key, {}).get(
                "sigma", config.SIGMA_F if config.LOCATIONS[city]["unit"] == "F" else config.SIGMA_C)
            new = round(mae, 3)
            cal[key] = {
                "sigma": new,
                "bias": round(bias, 3),
                "n": len(abs_errors),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if abs(new - old) > 0.05:
                updated.append(
                    f"{config.LOCATIONS[city]['name']} {source}: {old:.2f}->{new:.2f}")

    config.CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    if updated:
        print(f"  [CAL] {', '.join(updated)}")
    return cal
