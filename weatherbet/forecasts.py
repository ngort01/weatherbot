"""Forecast sources: Open-Meteo models, METAR, Visual Crossing actuals."""
import time
from datetime import datetime, timezone, timedelta

import requests

from weatherbet import config
from weatherbet.open_meteo_sources import (  # noqa: F401 — re-export for callers
    FORECAST_SOURCE_KEYS,
    HRRR_HORIZON_DAYS,
    OPEN_METEO_SOURCES,
)

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
METAR_URL = "https://aviationweather.gov/api/data/metar"
VC_TIMELINE = (
    "https://weather.visualcrossing.com/VisualCrossingWebServices"
    "/rest/services/timeline"
)

OPEN_METEO_TIMEOUT = (5, 10)
METAR_TIMEOUT = (5, 8)
VC_TIMEOUT = (5, 8)
HTTP_RETRIES = 3
RETRY_SLEEP_S = 3


def open_meteo_params(loc, city_slug, *, model, temp_unit, forecast_days,
                      bias_correction=False):
    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "daily": "temperature_2m_max",
        "temperature_unit": temp_unit,
        "forecast_days": forecast_days,
        "timezone": config.TIMEZONES.get(city_slug, "UTC"),
        "models": model,
    }
    if bias_correction:
        params["bias_correction"] = "true"
    return params


def metar_params(station):
    return {"ids": station, "format": "json"}


def visual_crossing_url(station, date_str):
    return f"{VC_TIMELINE}/{station}/{date_str}/{date_str}"


def visual_crossing_params(unit_group):
    return {
        "unitGroup": unit_group,
        "key": config.VC_KEY,
        "include": "days",
        "elements": "tempmax",
    }


def c_to_display(temp_c, unit):
    if unit == "F":
        return round(float(temp_c) * 9 / 5 + 32)
    return round(float(temp_c), 1)


def _round_fn_for_unit(unit):
    """Match historical ECMWF rounding: whole °F, one decimal °C."""
    if unit == "C":
        return lambda t: round(t, 1)
    return round


def _get_json(url, *, params=None, timeout=(5, 10), tag="", city_slug="",
              extra="", retries=HTTP_RETRIES):
    """GET JSON with retries on transport/parse errors. Returns None on failure."""
    for attempt in range(retries):
        try:
            return requests.get(url, params=params, timeout=timeout).json()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(RETRY_SLEEP_S)
            else:
                suffix = f" {extra}" if extra else ""
                print(f"  [{tag}] {city_slug}{suffix}: {e}")
    return None


def _parse_daily_maxes(data, dates, round_fn):
    if not data or "error" in data:
        return {}
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    temps = daily.get("temperature_2m_max") or []
    out = {}
    for date, temp in zip(times, temps):
        if date in dates and temp is not None:
            out[date] = round_fn(temp)
    return out


def _hrrr_horizon_date(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    return (now_utc + timedelta(days=HRRR_HORIZON_DAYS)).strftime("%Y-%m-%d")


def sources_for_region(region):
    """Open-Meteo snapshot keys applicable to a city region (including global)."""
    keys = []
    for key, cfg in OPEN_METEO_SOURCES.items():
        regions = cfg.get("regions")
        if regions is None or region in regions:
            keys.append(key)
    return keys


def pick_best(snap, region):
    """
    Trading selection (unchanged philosophy):
    HRRR for US when present, otherwise ECMWF.
    Extra regional sources are stored but not used here yet.
    """
    if region == "us" and snap.get("hrrr") is not None:
        return snap["hrrr"], "hrrr"
    if snap.get("ecmwf") is not None:
        return snap["ecmwf"], "ecmwf"
    return None, None


def get_open_meteo(city_slug, dates, source_key):
    """
    Fetch one registered Open-Meteo model for a city.
    Returns {} if source unknown, region mismatch, or fetch/parse empty.
    """
    cfg = OPEN_METEO_SOURCES.get(source_key)
    if not cfg:
        return {}
    loc = config.LOCATIONS[city_slug]
    regions = cfg.get("regions")
    if regions is not None and loc["region"] not in regions:
        return {}
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    # Preserve legacy HRRR behavior: always whole °F (US-only).
    if source_key == "hrrr":
        round_fn = round
    else:
        round_fn = _round_fn_for_unit(unit)
    data = _get_json(
        OPEN_METEO_FORECAST,
        params=open_meteo_params(
            loc, city_slug,
            model=cfg["model"],
            temp_unit=temp_unit,
            forecast_days=cfg.get("forecast_days", 7),
            bias_correction=bool(cfg.get("bias_correction")),
        ),
        timeout=OPEN_METEO_TIMEOUT,
        tag=cfg.get("tag", source_key.upper()),
        city_slug=city_slug,
    )
    return _parse_daily_maxes(data, dates, round_fn)


def get_ecmwf(city_slug, dates):
    """ECMWF via Open-Meteo with bias correction. For all cities."""
    return get_open_meteo(city_slug, dates, "ecmwf")


def get_hrrr(city_slug, dates):
    """HRRR via Open-Meteo. US cities only, up to 48h horizon."""
    return get_open_meteo(city_slug, dates, "hrrr")


def get_metar(city_slug):
    """Current observed temperature from METAR station. D+0 only."""
    loc = config.LOCATIONS[city_slug]
    try:
        data = requests.get(
            METAR_URL,
            params=metar_params(loc["station"]),
            timeout=METAR_TIMEOUT,
        ).json()
        if data and isinstance(data, list):
            temp_c = data[0].get("temp")
            if temp_c is not None:
                return c_to_display(temp_c, loc["unit"])
    except Exception as e:
        print(f"  [METAR] {city_slug}: {e}")
    return None


def get_actual_temp(city_slug, date_str):
    """Actual temperature via Visual Crossing for closed markets."""
    loc = config.LOCATIONS[city_slug]
    unit = loc["unit"]
    vc_unit = "us" if unit == "F" else "metric"
    try:
        data = requests.get(
            visual_crossing_url(loc["station"], date_str),
            params=visual_crossing_params(vc_unit),
            timeout=VC_TIMEOUT,
        ).json()
        days = data.get("days", [])
        if days and days[0].get("tempmax") is not None:
            return round(float(days[0]["tempmax"]), 1)
    except Exception as e:
        print(f"  [VC] {city_slug} {date_str}: {e}")
    return None


def persistable_forecast_snap(snap, horizon, hours_left):
    """
    Market-file forecast_snapshots entry: meta + every source key present on snap.
    Keeps region-specific models (icon, gem, …) instead of a hard-coded whitelist.
    """
    out = {
        "ts": snap.get("ts"),
        "horizon": horizon,
        "hours_left": round(hours_left, 1),
        "best": snap.get("best"),
        "best_source": snap.get("best_source"),
    }
    for k in FORECAST_SOURCE_KEYS:
        if k in snap:
            out[k] = snap[k]
    return out


def take_forecast_snapshot(city_slug, dates):
    """
    Fetches forecasts from all region-applicable sources and returns a snapshot.
    Extra regional models are stored for later use; pick_best is unchanged.
    """

    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    region = config.LOCATIONS[city_slug]["region"]
    source_keys = sources_for_region(region)

    by_source = {}
    for key in source_keys:
        by_source[key] = get_open_meteo(city_slug, dates, key)

    metar = get_metar(city_slug) if today in dates else None
    horizon_by_key = {}
    for key in source_keys:
        max_h = OPEN_METEO_SOURCES[key].get("max_horizon_days")
        if max_h is not None:
            horizon_by_key[key] = (
                now + timedelta(days=max_h)
            ).strftime("%Y-%m-%d")

    snapshots = {}
    for date in dates:
        snap = {"ts": now_str}
        for key in source_keys:
            temp = by_source[key].get(date)
            until = horizon_by_key.get(key)
            if until is not None and date > until:
                temp = None
            snap[key] = temp
        snap["metar"] = metar if date == today else None
        best, source = pick_best(snap, region)
        snap["best"] = best
        snap["best_source"] = source
        snapshots[date] = snap
    return snapshots
