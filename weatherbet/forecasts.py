"""Forecast sources: ECMWF, HRRR/GFS, METAR, Visual Crossing actuals."""
import time
from datetime import datetime, timezone, timedelta

import requests

from weatherbet import config

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
HRRR_HORIZON_DAYS = 2


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


def pick_best(snap, region):
    """Best forecast: HRRR for US when present, otherwise ECMWF. Pure."""
    if region == "us" and snap.get("hrrr") is not None:
        return snap["hrrr"], "hrrr"
    if snap.get("ecmwf") is not None:
        return snap["ecmwf"], "ecmwf"
    return None, None


def get_ecmwf(city_slug, dates):
    """ECMWF via Open-Meteo with bias correction. For all cities."""
    loc = config.LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    round_fn = (lambda t: round(t, 1)) if unit == "C" else round
    data = _get_json(
        OPEN_METEO_FORECAST,
        params=open_meteo_params(
            loc, city_slug,
            model="ecmwf_ifs025",
            temp_unit=temp_unit,
            forecast_days=7,
            bias_correction=True,
        ),
        timeout=OPEN_METEO_TIMEOUT,
        tag="ECMWF",
        city_slug=city_slug,
    )
    return _parse_daily_maxes(data, dates, round_fn)


def get_hrrr(city_slug, dates):
    """HRRR via Open-Meteo. US cities only, up to 48h horizon."""
    loc = config.LOCATIONS[city_slug]
    if loc["region"] != "us":
        return {}
    data = _get_json(
        OPEN_METEO_FORECAST,
        params=open_meteo_params(
            loc, city_slug,
            model="gfs_seamless",  # HRRR+GFS seamless — best option for US
            temp_unit="fahrenheit",
            forecast_days=3,
        ),
        timeout=OPEN_METEO_TIMEOUT,
        tag="HRRR",
        city_slug=city_slug,
    )
    return _parse_daily_maxes(data, dates, round)


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


def take_forecast_snapshot(city_slug, dates):
    """Fetches forecasts from all sources and returns a snapshot."""
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    today = now.strftime("%Y-%m-%d")
    hrrr_until = _hrrr_horizon_date(now)
    region = config.LOCATIONS[city_slug]["region"]

    ecmwf = get_ecmwf(city_slug, dates)
    hrrr = get_hrrr(city_slug, dates)
    metar = get_metar(city_slug) if today in dates else None

    snapshots = {}
    for date in dates:
        snap = {
            "ts": now_str,
            "ecmwf": ecmwf.get(date),
            "hrrr": hrrr.get(date) if date <= hrrr_until else None,
            "metar": metar if date == today else None,
        }
        best, source = pick_best(snap, region)
        snap["best"] = best
        snap["best_source"] = source
        snapshots[date] = snap
    return snapshots
