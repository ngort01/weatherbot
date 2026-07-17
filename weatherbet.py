#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weatherbet.py — Weather Trading Bot for Polymarket
=====================================================
Tracks weather forecasts from 3 sources (ECMWF, HRRR, METAR),
compares with Polymarket markets, paper trades using Kelly criterion.

Usage:
    python weatherbet.py          # main loop
    python weatherbet.py scan     # dry-run: show markets + would-be trades (no fills)
    python weatherbet.py status   # balance and open positions
    python weatherbet.py report   # full report
    python weatherbet.py reconcile [--fix]  # audit (or repair) balance vs market files
    python weatherbet.py refresh             # rebuild portfolio KPIs in state.json from markets
"""

import os
import re
import sys
import json
import math
import time
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# =============================================================================
# CONFIG
# =============================================================================

load_dotenv()

with open("config.json", encoding="utf-8") as f:
    _cfg = json.load(f)

BALANCE = _cfg.get("balance", 10000.0)
MAX_BET = _cfg.get("max_bet", 20.0)        # max bet per trade
MIN_EV = _cfg.get("min_ev", 0.10)
MAX_PRICE = _cfg.get("max_price", 0.45)
MIN_VOLUME = _cfg.get("min_volume", 500)
MIN_HOURS = _cfg.get("min_hours", 2.0)
MAX_HOURS = _cfg.get("max_hours", 72.0)
KELLY_FRACTION = _cfg.get("kelly_fraction", 0.25)
MAX_SLIPPAGE = _cfg.get("max_slippage", 0.03)  # max allowed ask-bid spread
SCAN_INTERVAL = _cfg.get("scan_interval", 3600)   # every hour
CALIBRATION_MIN = _cfg.get("calibration_min", 30)
# Portfolio risk caps (IMPROVEMENTS §3)
MAX_OPEN_POSITIONS = int(_cfg.get("max_open_positions", 20))
MAX_OPEN_PER_CITY = int(_cfg.get("max_open_per_city", 2))
MAX_OPEN_PER_DATE = int(_cfg.get("max_open_per_date", 6))
MAX_CAPITAL_AT_RISK_PCT = float(_cfg.get("max_capital_at_risk_pct", 0.2))
# Secret lives in .env — never config.json
VC_KEY = os.getenv("VC_KEY", _cfg.get("vc_key", ""))

SIGMA_F = 2.0
SIGMA_C = 1.2

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
MARKETS_DIR = DATA_DIR / "markets"
MARKETS_DIR.mkdir(exist_ok=True)
CALIBRATION_FILE = DATA_DIR / "calibration.json"

LOCATIONS = {
    "nyc":          {"lat": 40.7772,  "lon": -73.8726, "name": "New York City", "station": "KLGA", "unit": "F", "region": "us"},
    "chicago":      {"lat": 41.9742,  "lon": -87.9073, "name": "Chicago",       "station": "KORD", "unit": "F", "region": "us"},
    "miami":        {"lat": 25.7959,  "lon": -80.2870, "name": "Miami",         "station": "KMIA", "unit": "F", "region": "us"},
    "dallas":       {"lat": 32.8471,  "lon": -96.8518, "name": "Dallas",        "station": "KDAL", "unit": "F", "region": "us"},
    "seattle":      {"lat": 47.4502,  "lon": -122.3088, "name": "Seattle",       "station": "KSEA", "unit": "F", "region": "us"},
    "atlanta":      {"lat": 33.6407,  "lon": -84.4277, "name": "Atlanta",       "station": "KATL", "unit": "F", "region": "us"},
    "london":       {"lat": 51.5048,  "lon":    0.0495, "name": "London",        "station": "EGLC", "unit": "C", "region": "eu"},
    "paris":        {"lat": 48.9962,  "lon":    2.5979, "name": "Paris",         "station": "LFPG", "unit": "C", "region": "eu"},
    "munich":       {"lat": 48.3537,  "lon":   11.7750, "name": "Munich",        "station": "EDDM", "unit": "C", "region": "eu"},
    "ankara":       {"lat": 40.1281,  "lon":   32.9951, "name": "Ankara",        "station": "LTAC", "unit": "C", "region": "eu"},
    "seoul":        {"lat": 37.4691,  "lon":  126.4505, "name": "Seoul",         "station": "RKSI", "unit": "C", "region": "asia"},
    "tokyo":        {"lat": 35.7647,  "lon":  140.3864, "name": "Tokyo",         "station": "RJTT", "unit": "C", "region": "asia"},
    "shanghai":     {"lat": 31.1443,  "lon":  121.8083, "name": "Shanghai",      "station": "ZSPD", "unit": "C", "region": "asia"},
    "singapore":    {"lat":  1.3502,  "lon":  103.9940, "name": "Singapore",     "station": "WSSS", "unit": "C", "region": "asia"},
    "lucknow":      {"lat": 26.7606,  "lon":   80.8893, "name": "Lucknow",       "station": "VILK", "unit": "C", "region": "asia"},
    "tel-aviv":     {"lat": 32.0114,  "lon":   34.8867, "name": "Tel Aviv",      "station": "LLBG", "unit": "C", "region": "asia"},
    "toronto":      {"lat": 43.6772,  "lon": -79.6306, "name": "Toronto",       "station": "CYYZ", "unit": "C", "region": "ca"},
    "sao-paulo":    {"lat": -23.4356, "lon": -46.4731, "name": "Sao Paulo",     "station": "SBGR", "unit": "C", "region": "sa"},
    "buenos-aires": {"lat": -34.8222, "lon": -58.5358, "name": "Buenos Aires",  "station": "SAEZ", "unit": "C", "region": "sa"},
    "wellington":   {"lat": -41.3272, "lon":  174.8052, "name": "Wellington",    "station": "NZWN", "unit": "C", "region": "oc"},
}

TIMEZONES = {
    "nyc": "America/New_York", "chicago": "America/Chicago",
    "miami": "America/New_York", "dallas": "America/Chicago",
    "seattle": "America/Los_Angeles", "atlanta": "America/New_York",
    "london": "Europe/London", "paris": "Europe/Paris",
    "munich": "Europe/Berlin", "ankara": "Europe/Istanbul",
    "seoul": "Asia/Seoul", "tokyo": "Asia/Tokyo",
    "shanghai": "Asia/Shanghai", "singapore": "Asia/Singapore",
    "lucknow": "Asia/Kolkata", "tel-aviv": "Asia/Jerusalem",
    "toronto": "America/Toronto", "sao-paulo": "America/Sao_Paulo",
    "buenos-aires": "America/Argentina/Buenos_Aires", "wellington": "Pacific/Auckland",
}

MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]

# =============================================================================
# MATH
# =============================================================================


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bucket_prob(forecast, t_low, t_high, sigma=None):
    """For regular buckets — exact match. For edge buckets — normal distribution."""
    s = sigma or 2.0
    if t_low == -999:
        return norm_cdf((t_high - float(forecast)) / s)
    if t_high == 999:
        return 1.0 - norm_cdf((t_low - float(forecast)) / s)
    return 1.0 if in_bucket(forecast, t_low, t_high) else 0.0


def calc_ev(p, price):
    if price <= 0 or price >= 1:
        return 0.0
    return round(p * (1.0 / price - 1.0) - (1.0 - p), 4)


def calc_kelly(p, price):
    if price <= 0 or price >= 1:
        return 0.0
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(0.0, f) * KELLY_FRACTION, 1.0), 4)


def bet_size(kelly, balance):
    raw = kelly * balance
    return round(min(raw, MAX_BET), 2)

# =============================================================================
# CALIBRATION
# =============================================================================


_cal: dict = {}


def load_cal():
    if CALIBRATION_FILE.exists():
        return json.loads(CALIBRATION_FILE.read_text(encoding="utf-8"))
    return {}


def get_sigma(city_slug, source="ecmwf"):
    key = f"{city_slug}_{source}"
    if key in _cal:
        return _cal[key]["sigma"]
    return SIGMA_F if LOCATIONS[city_slug]["unit"] == "F" else SIGMA_C


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
            if len(abs_errors) < CALIBRATION_MIN:
                continue
            mae = sum(abs_errors) / len(abs_errors)
            bias = sum(signed_errors) / len(signed_errors)
            key = f"{city}_{source}"
            old = cal.get(key, {}).get(
                "sigma", SIGMA_F if LOCATIONS[city]["unit"] == "F" else SIGMA_C)
            new = round(mae, 3)
            cal[key] = {
                "sigma": new,
                "bias": round(bias, 3),
                "n": len(abs_errors),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if abs(new - old) > 0.05:
                updated.append(
                    f"{LOCATIONS[city]['name']} {source}: {old:.2f}->{new:.2f}")

    CALIBRATION_FILE.write_text(json.dumps(cal, indent=2), encoding="utf-8")
    if updated:
        print(f"  [CAL] {', '.join(updated)}")
    return cal


# =============================================================================
# PORTFOLIO RISK
# =============================================================================


def portfolio_snapshot(markets=None):
    """Aggregate open positions: counts and capital at risk (sum of costs)."""
    if markets is None:
        markets = load_all_markets()
    total = 0
    by_city = {}
    by_date = {}
    capital = 0.0
    for m in markets:
        pos = m.get("position") or {}
        if pos.get("status") != "open":
            continue
        total += 1
        city = m["city"]
        date = m["date"]
        by_city[city] = by_city.get(city, 0) + 1
        by_date[date] = by_date.get(date, 0) + 1
        capital += float(pos.get("cost") or 0.0)
    return {
        "total": total,
        "by_city": by_city,
        "by_date": by_date,
        "capital": capital,
    }


def risk_limit_reason(city_slug, date_str, cost, balance, book):
    """
    Return a human-readable skip reason if opening would breach portfolio caps,
    else None. `book` is a portfolio_snapshot dict (mutated by caller on open/close).
    """
    if book["total"] >= MAX_OPEN_POSITIONS:
        return f"max open positions ({MAX_OPEN_POSITIONS})"
    if book["by_city"].get(city_slug, 0) >= MAX_OPEN_PER_CITY:
        return f"max open per city ({MAX_OPEN_PER_CITY})"
    if book["by_date"].get(date_str, 0) >= MAX_OPEN_PER_DATE:
        return f"max open per date ({MAX_OPEN_PER_DATE})"
    equity = balance + book["capital"]
    if equity <= 0:
        return "no equity"
    if (book["capital"] + cost) / equity > MAX_CAPITAL_AT_RISK_PCT + 1e-12:
        return f"max capital at risk ({MAX_CAPITAL_AT_RISK_PCT:.0%})"
    return None


def book_register_open(book, city_slug, date_str, cost):
    book["total"] += 1
    book["by_city"][city_slug] = book["by_city"].get(city_slug, 0) + 1
    book["by_date"][date_str] = book["by_date"].get(date_str, 0) + 1
    book["capital"] += float(cost)


def book_register_close(book, city_slug, date_str, cost):
    book["total"] = max(0, book["total"] - 1)
    if city_slug in book["by_city"]:
        book["by_city"][city_slug] = max(0, book["by_city"][city_slug] - 1)
    if date_str in book["by_date"]:
        book["by_date"][date_str] = max(0, book["by_date"][date_str] - 1)
    book["capital"] = max(0.0, book["capital"] - float(cost))

# =============================================================================
# FORECASTS
# =============================================================================


def get_ecmwf(city_slug, dates):
    """ECMWF via Open-Meteo with bias correction. For all cities."""
    loc = LOCATIONS[city_slug]
    unit = loc["unit"]
    temp_unit = "fahrenheit" if unit == "F" else "celsius"
    result = {}
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily=temperature_2m_max&temperature_unit={temp_unit}"
        f"&forecast_days=7&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        f"&models=ecmwf_ifs025&bias_correction=true"
    )
    for attempt in range(3):
        try:
            data = requests.get(url, timeout=(5, 10)).json()
            if "error" not in data:
                for date, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                    if date in dates and temp is not None:
                        result[date] = round(
                            temp, 1) if unit == "C" else round(temp)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"  [ECMWF] {city_slug}: {e}")
    return result


def get_hrrr(city_slug, dates):
    """HRRR via Open-Meteo. US cities only, up to 48h horizon."""
    loc = LOCATIONS[city_slug]
    if loc["region"] != "us":
        return {}
    result = {}
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={loc['lat']}&longitude={loc['lon']}"
        f"&daily=temperature_2m_max&temperature_unit=fahrenheit"
        f"&forecast_days=3&timezone={TIMEZONES.get(city_slug, 'UTC')}"
        f"&models=gfs_seamless"  # HRRR+GFS seamless — best option for US
    )
    for attempt in range(3):
        try:
            data = requests.get(url, timeout=(5, 10)).json()
            if "error" not in data:
                for date, temp in zip(data["daily"]["time"], data["daily"]["temperature_2m_max"]):
                    if date in dates and temp is not None:
                        result[date] = round(temp)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"  [HRRR] {city_slug}: {e}")
    return result


def get_metar(city_slug):
    """Current observed temperature from METAR station. D+0 only."""
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    try:
        url = f"https://aviationweather.gov/api/data/metar?ids={station}&format=json"
        data = requests.get(url, timeout=(5, 8)).json()
        if data and isinstance(data, list):
            temp_c = data[0].get("temp")
            if temp_c is not None:
                if unit == "F":
                    return round(float(temp_c) * 9/5 + 32)
                return round(float(temp_c), 1)
    except Exception as e:
        print(f"  [METAR] {city_slug}: {e}")
    return None


def get_actual_temp(city_slug, date_str):
    """Actual temperature via Visual Crossing for closed markets."""
    loc = LOCATIONS[city_slug]
    station = loc["station"]
    unit = loc["unit"]
    vc_unit = "us" if unit == "F" else "metric"
    url = (
        f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
        f"/{station}/{date_str}/{date_str}"
        f"?unitGroup={vc_unit}&key={VC_KEY}&include=days&elements=tempmax"
    )
    try:
        data = requests.get(url, timeout=(5, 8)).json()
        days = data.get("days", [])
        if days and days[0].get("tempmax") is not None:
            return round(float(days[0]["tempmax"]), 1)
    except Exception as e:
        print(f"  [VC] {city_slug} {date_str}: {e}")
    return None


def check_market_resolved(market_id):
    """
    Checks if the market closed on Polymarket and who won.
    Returns: None (still open), True (YES won), False (NO won)
    """
    try:
        r = requests.get(
            f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=(5, 8))
        data = r.json()
        closed = data.get("closed", False)
        if not closed:
            return None
        # Check YES price — if ~1.0 then WIN, if ~0.0 then LOSS
        prices = json.loads(data.get("outcomePrices", "[0.5,0.5]"))
        yes_price = float(prices[0])
        if yes_price >= 0.95:
            return True   # WIN
        elif yes_price <= 0.05:
            return False  # LOSS
        return None  # not yet determined
    except Exception as e:
        print(f"  [RESOLVE] {market_id}: {e}")
    return None

# =============================================================================
# POLYMARKET
# =============================================================================


def get_polymarket_event(city_slug, month, day, year):
    slug = f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"
    try:
        r = requests.get(
            f"https://gamma-api.polymarket.com/events?slug={slug}", timeout=(5, 8))
        data = r.json()
        if data and isinstance(data, list) and len(data) > 0:
            return data[0]
    except Exception:
        pass
    return None


def get_market_price(market_id):
    try:
        r = requests.get(
            f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=(3, 5))
        prices = json.loads(r.json().get("outcomePrices", "[0.5,0.5]"))
        return float(prices[0])
    except Exception:
        return None


def parse_temp_range(question):
    if not question:
        return None
    num = r'(-?\d+(?:\.\d+)?)'
    if re.search(r'or below', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or below', question, re.IGNORECASE)
        if m:
            return (-999.0, float(m.group(1)))
    if re.search(r'or higher', question, re.IGNORECASE):
        m = re.search(num + r'[°]?[FC] or higher', question, re.IGNORECASE)
        if m:
            return (float(m.group(1)), 999.0)
    m = re.search(r'between ' + num + r'-' + num +
                  r'[°]?[FC]', question, re.IGNORECASE)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = re.search(r'be ' + num + r'[°]?[FC] on', question, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return (v, v)
    return None


def hours_to_resolution(end_date_str):
    try:
        end = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        return max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return 999.0


def in_bucket(forecast, t_low, t_high):
    if t_low == t_high:
        return round(float(forecast)) == round(t_low)
    return t_low <= float(forecast) <= t_high

# =============================================================================
# MARKET DATA STORAGE
# Each market is stored in a separate file: data/markets/{city}_{date}.json
# =============================================================================


def market_path(city_slug, date_str):
    return MARKETS_DIR / f"{city_slug}_{date_str}.json"


def load_market(city_slug, date_str):
    p = market_path(city_slug, date_str)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_market(market):
    p = market_path(market["city"], market["date"])
    p.write_text(json.dumps(market, indent=2,
                 ensure_ascii=False), encoding="utf-8")


def load_all_markets():
    markets = []
    for f in MARKETS_DIR.glob("*.json"):
        try:
            markets.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return markets


def new_market(city_slug, date_str, event, hours):
    loc = LOCATIONS[city_slug]
    return {
        "city":               city_slug,
        "city_name":          loc["name"],
        "date":               date_str,
        "unit":               loc["unit"],
        "station":            loc["station"],
        "event_end_date":     event.get("endDate", ""),
        "hours_at_discovery": round(hours, 1),
        "status":             "open",           # open | closed | resolved
        "position":           None,             # filled when position opens
        "actual_temp":        None,             # filled after resolution
        "resolved_outcome":   None,             # win / loss / no_position
        "pnl":                None,
        "forecast_snapshots": [],               # list of forecast snapshots
        "market_snapshots":   [],               # list of market price snapshots
        "all_outcomes":       [],               # all market buckets
        "created_at":         datetime.now(timezone.utc).isoformat(),
    }

# =============================================================================
# STATE (balance and open positions)
# =============================================================================


def default_state():
    """Fresh paper-bankroll state (cash fields + portfolio summary placeholders)."""
    return {
        "balance":          BALANCE,
        "starting_balance": BALANCE,
        "peak_balance":     BALANCE,
        "total_trades":     0,
        "wins":             0,   # held-to-resolution only
        "losses":           0,   # held-to-resolution only
        # Filled by refresh_state_stats from market files:
        "updated_at":       None,
        "realized_pnl":     0.0,
        "closed_count":     0,
        "open_count":       0,
        "open_capital":     0.0,
        "equity":           BALANCE,
        "return_pct":       0.0,
        "drawdown_pct":     0.0,
        "exits":            {},
        "bucket_outcomes":  {"win": 0, "loss": 0, "pending": 0},
        "hold_vs_exit":     {
            "annotated": 0,
            "exit_pnl_sum": 0.0,
            "hold_pnl_sum": 0.0,
            "hold_minus_exit": 0.0,
        },
        "actuals_count":    0,
    }


def load_state():
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # Backfill keys missing from older state.json files
        base = default_state()
        for k, v in base.items():
            if k not in state:
                state[k] = v
        return state
    return default_state()


def save_state(state):
    STATE_FILE.write_text(json.dumps(
        state, indent=2, ensure_ascii=False), encoding="utf-8")


def balance_from_markets(markets, starting_balance):
    """
    Ground-truth paper cash from market files.

    Open position: cost still locked → cash reduced by cost.
    Closed position: cost returned ± realized pnl.
    """
    total_cost = 0.0
    total_returned = 0.0
    n_open = 0
    n_closed = 0
    for m in markets:
        pos = m.get("position")
        if not pos:
            continue
        cost = float(pos.get("cost") or 0.0)
        total_cost += cost
        if pos.get("status") == "closed":
            n_closed += 1
            pnl = pos.get("pnl")
            total_returned += cost + (float(pnl) if pnl is not None else 0.0)
        else:
            n_open += 1
    balance = round(float(starting_balance) - total_cost + total_returned, 2)
    return {
        "balance": balance,
        "starting_balance": float(starting_balance),
        "total_cost": round(total_cost, 2),
        "total_returned": round(total_returned, 2),
        "n_open": n_open,
        "n_closed": n_closed,
    }


def compute_portfolio_stats(markets, starting_balance, balance, peak_balance):
    """
    Derive portfolio KPIs from market files + current cash/peak.

    Market files are source of truth for trades; balance/peak come from state.
    """
    start = float(starting_balance)
    bal = float(balance)
    peak = float(peak_balance) if peak_balance else start

    n_open = 0
    n_closed = 0
    open_capital = 0.0
    realized_pnl = 0.0
    exits = {}
    bucket_win = bucket_loss = bucket_pending = 0
    held_wins = held_losses = 0
    hv_n = 0
    hv_exit = 0.0
    hv_hold = 0.0
    actuals = 0

    for m in markets:
        if m.get("actual_temp") is not None:
            actuals += 1
        pos = m.get("position")
        if not pos:
            continue

        cost = float(pos.get("cost") or 0.0)
        status = pos.get("status")
        outcome = m.get("resolved_outcome")

        if status == "closed":
            n_closed += 1
            pnl = float(pos.get("pnl") or 0.0)
            realized_pnl += pnl
            reason = pos.get("close_reason") or "unknown"
            slot = exits.setdefault(reason, {"n": 0, "pnl": 0.0})
            slot["n"] += 1
            slot["pnl"] = round(slot["pnl"] + pnl, 2)

            if outcome == "win":
                bucket_win += 1
            elif outcome == "loss":
                bucket_loss += 1
            else:
                bucket_pending += 1

            # Held-to-resolution settlements (bankroll path)
            if (m.get("held_to_resolution") is True
                    or pos.get("close_reason") == "resolved"):
                if outcome == "win":
                    held_wins += 1
                elif outcome == "loss":
                    held_losses += 1

            # Counterfactual: early exit vs hold (needs annotation)
            hold_pnl = m.get("hold_to_resolution_pnl")
            if (hold_pnl is not None and outcome in ("win", "loss")
                    and pos.get("close_reason") != "resolved"):
                hv_n += 1
                hv_exit += pnl
                hv_hold += float(hold_pnl)
        else:
            n_open += 1
            open_capital += cost
            if outcome is None:
                bucket_pending += 1
            elif outcome == "win":
                bucket_win += 1
            elif outcome == "loss":
                bucket_loss += 1

    equity = round(bal + open_capital, 2)
    ret_pct = round((equity - start) / start * 100, 2) if start else 0.0
    dd_pct = 0.0
    if peak > 0:
        dd_pct = round(max(0.0, (peak - bal) / peak * 100), 2)

    # Round exit pnls
    exits_out = {
        k: {"n": v["n"], "pnl": round(v["pnl"], 2)}
        for k, v in sorted(exits.items())
    }

    return {
        "total_trades": n_open + n_closed,
        "wins": held_wins,
        "losses": held_losses,
        "realized_pnl": round(realized_pnl, 2),
        "closed_count": n_closed,
        "open_count": n_open,
        "open_capital": round(open_capital, 2),
        "equity": equity,
        "return_pct": ret_pct,
        "drawdown_pct": dd_pct,
        "exits": exits_out,
        "bucket_outcomes": {
            "win": bucket_win,
            "loss": bucket_loss,
            "pending": bucket_pending,
        },
        "hold_vs_exit": {
            "annotated": hv_n,
            "exit_pnl_sum": round(hv_exit, 2),
            "hold_pnl_sum": round(hv_hold, 2),
            "hold_minus_exit": round(hv_hold - hv_exit, 2),
        },
        "actuals_count": actuals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def refresh_state_stats(state=None, markets=None, write=True):
    """
    Recompute portfolio summary fields on state from market files.

    Does not change balance / starting_balance / peak_balance (cash ledger).
    total_trades / wins / losses are rebuilt from markets so they cannot drift.
    """
    if state is None:
        state = load_state()
    if markets is None:
        markets = load_all_markets()

    start = float(state.get("starting_balance", BALANCE))
    bal = float(state.get("balance", start))
    peak = float(state.get("peak_balance", bal))
    stats = compute_portfolio_stats(markets, start, bal, peak)

    for k, v in stats.items():
        state[k] = v

    if write:
        save_state(state)
    return state


def reconcile_balance(apply=False, markets=None, state=None):
    """
    Compare state.json balance to trade reconstruction from market files.

    If apply=True and they differ, rewrite balance (and lower peak_balance when
    it was only inflated by the bad cash figure). Always refreshes portfolio
    stats when apply=True. Returns a report dict.
    """
    if state is None:
        state = load_state()
    if markets is None:
        markets = load_all_markets()

    start = float(state.get("starting_balance", BALANCE))
    stored = round(float(state.get("balance", start)), 2)
    rebuilt = balance_from_markets(markets, start)
    true_bal = rebuilt["balance"]
    delta = round(stored - true_bal, 2)
    peak = float(state.get("peak_balance", stored))
    # True high-water mark is not recoverable after inflation; use a conservative
    # peak so drawdown is not fake-zero. Always peak >= true cash.
    peak_fixed = max(start, true_bal)

    report = {
        "stored_balance": stored,
        "true_balance": true_bal,
        "delta": delta,
        "ok": abs(delta) < 0.005,
        "peak_balance": peak,
        "peak_balance_fixed": round(peak_fixed, 2),
        "n_open": rebuilt["n_open"],
        "n_closed": rebuilt["n_closed"],
        "applied": False,
    }

    if apply and not report["ok"]:
        state["balance"] = true_bal
        state["peak_balance"] = round(peak_fixed, 2)
        report["applied"] = True
        report["peak_balance"] = float(state["peak_balance"])

    if apply:
        # Persist cash fix (if any) + full portfolio summary from markets
        refresh_state_stats(state=state, markets=markets, write=True)

    return report


def print_reconcile(apply=False):
    """CLI: show state vs market-file cash; optionally rewrite state.json."""
    report = reconcile_balance(apply=apply)
    print(f"\n{'='*55}")
    print(f"  WEATHERBET — BALANCE RECONCILE")
    print(f"{'='*55}")
    print(f"  Market files:  {report['n_open']} open | {report['n_closed']} closed")
    print(f"  state.json:    ${report['stored_balance']:,.2f}")
    print(f"  From trades:   ${report['true_balance']:,.2f}")
    print(f"  Delta:         {'+' if report['delta'] >= 0 else ''}"
          f"{report['delta']:,.2f}")
    if report["ok"]:
        print(f"  Status:        OK — balance matches market files")
        if apply:
            print(f"  Stats:         refreshed portfolio summary from markets")
    elif report["applied"]:
        print(f"  Status:        FIXED — wrote true balance to state.json")
        print(f"  peak_balance:  ${report['peak_balance']:,.2f}")
    else:
        print(f"  Status:        DRIFT — run with --fix to rewrite state.json")
        print(f"  peak_balance:  ${report['peak_balance']:,.2f} "
              f"(would become ${report['peak_balance_fixed']:,.2f})")
    print(f"{'='*55}\n")
    return report

# =============================================================================
# CORE LOGIC
# =============================================================================


def take_forecast_snapshot(city_slug, dates):
    """Fetches forecasts from all sources and returns a snapshot."""
    now_str = datetime.now(timezone.utc).isoformat()
    ecmwf = get_ecmwf(city_slug, dates)
    hrrr = get_hrrr(city_slug, dates)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    snapshots = {}
    for date in dates:
        snap = {
            "ts":    now_str,
            "ecmwf": ecmwf.get(date),
            "hrrr":  hrrr.get(date) if date <= (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d") else None,
            "metar": get_metar(city_slug) if date == today else None,
        }
        # Best forecast: HRRR for US D+0/D+1, otherwise ECMWF
        loc = LOCATIONS[city_slug]
        if loc["region"] == "us" and snap["hrrr"] is not None:
            snap["best"] = snap["hrrr"]
            snap["best_source"] = "hrrr"
        elif snap["ecmwf"] is not None:
            snap["best"] = snap["ecmwf"]
            snap["best_source"] = "ecmwf"
        else:
            snap["best"] = None
            snap["best_source"] = None
        snapshots[date] = snap
    return snapshots


def parse_event_outcomes(event):
    """
    Parse Gamma event markets into outcome dicts.

    IMPORTANT: Gamma `outcomePrices` is [YES, NO] last/mid-style prices that
    sum ~1 — NOT CLOB bestBid/bestAsk. We keep legacy keys bid/ask as
    yes_price / no_price aliases for compatibility, but entry sizing must
    re-fetch bestBid/bestAsk (see consider_entry).
    """
    outcomes = []
    for market in event.get("markets", []):
        question = market.get("question", "")
        mid = str(market.get("id", ""))
        volume = float(market.get("volume", 0))
        rng = parse_temp_range(question)
        if not rng:
            continue
        try:
            prices = json.loads(market.get("outcomePrices", "[0.5,0.5]"))
            yes_price = float(prices[0])
            no_price = float(prices[1]) if len(prices) > 1 else (1.0 - yes_price)
        except Exception:
            continue
        outcomes.append({
            "question":   question,
            "market_id":  mid,
            "range":      rng,
            # Canonical names
            "yes_price":  round(yes_price, 4),
            "no_price":   round(no_price, 4),
            # Legacy aliases (misnamed — not real bid/ask)
            "bid":        round(yes_price, 4),
            "ask":        round(no_price, 4),
            "price":      round(yes_price, 4),
            "spread":     round(abs(no_price - yes_price), 4),
            "volume":     round(volume, 0),
        })
    outcomes.sort(key=lambda x: x["range"][0])
    return outcomes


def consider_entry(
    city_slug,
    date_str,
    outcomes,
    forecast_temp,
    best_source,
    hours,
    balance,
    book,
    *,
    opened_at=None,
    fetch_live_book=True,
):
    """
    Evaluate opening YES on the single forecast-matched bucket.

    Returns (signal_or_None, skip_reason_or_None).
    Does not mutate book, balance, or market files.
    When signal is returned, skip_reason is None and the caller may open (or preview).
    """
    if forecast_temp is None:
        return None, "no forecast"
    if hours < MIN_HOURS:
        return None, f"hours {hours:.1f} < min {MIN_HOURS}"
    if hours > MAX_HOURS:
        return None, f"hours {hours:.1f} > max {MAX_HOURS}"

    matched = None
    for o in outcomes:
        t_low, t_high = o["range"]
        if in_bucket(forecast_temp, t_low, t_high):
            matched = o
            break
    if not matched:
        return None, "no matching bucket"

    t_low, t_high = matched["range"]
    volume = matched["volume"]
    # outcomePrices are YES/NO — only useful as a rough mid until live book
    yes_mid = matched.get(
        "yes_price", matched.get("bid", matched.get("price", 0.5))
    )

    if volume < MIN_VOLUME:
        return None, f"volume {volume:.0f} < min {MIN_VOLUME}"

    sigma = get_sigma(city_slug, best_source or "ecmwf")
    p = bucket_prob(forecast_temp, t_low, t_high, sigma)

    # Provisional size from bankroll/kelly; final EV/shares use entry price
    # (live bestAsk when available — never NO price from outcomePrices).
    provisional_price = yes_mid if 0 < yes_mid < 1 else 0.5
    kelly = calc_kelly(p, provisional_price)
    size = bet_size(kelly, balance)
    if size < 0.50:
        return None, f"size ${size:.2f} < $0.50"

    signal = {
        "market_id":     matched["market_id"],
        "question":      matched["question"],
        "bucket_low":    t_low,
        "bucket_high":   t_high,
        "entry_price":   provisional_price,
        "bid_at_entry":  provisional_price,
        "spread":        None,
        "shares":        round(size / provisional_price, 2),
        "cost":          size,
        "p":             round(p, 4),
        "ev":            round(calc_ev(p, provisional_price), 4),
        "kelly":         round(kelly, 4),
        "forecast_temp": forecast_temp,
        "forecast_src":  best_source,
        "sigma":         sigma,
        "opened_at":     opened_at,
        "status":        "open",
        "pnl":           None,
        "exit_price":    None,
        "close_reason":  None,
        "closed_at":     None,
        "stop_price":    round(provisional_price * 0.80, 4),
        "book_source":   "yes_mid",  # upgraded to "clob" after live fetch
    }

    if fetch_live_book:
        try:
            r = requests.get(
                f"https://gamma-api.polymarket.com/markets/{signal['market_id']}",
                timeout=(3, 5),
            )
            mdata = r.json()
            real_ask = float(mdata.get("bestAsk", signal["entry_price"]))
            real_bid = float(mdata.get("bestBid", signal["bid_at_entry"]))
            real_spread = round(real_ask - real_bid, 4)
            if real_spread > MAX_SLIPPAGE or real_ask >= MAX_PRICE:
                return None, (
                    f"real ask ${real_ask:.3f} spread ${real_spread:.3f}"
                )
            if real_ask <= 0:
                return None, "invalid live ask"
            signal["entry_price"] = real_ask
            signal["bid_at_entry"] = real_bid
            signal["spread"] = real_spread
            signal["shares"] = round(signal["cost"] / real_ask, 2)
            signal["ev"] = round(calc_ev(signal["p"], real_ask), 4)
            signal["kelly"] = round(calc_kelly(signal["p"], real_ask), 4)
            signal["stop_price"] = round(real_ask * 0.80, 4)
            signal["book_source"] = "clob"
        except Exception as e:
            # No trustworthy ask — do not pretend NO-price is a buy price
            return None, f"live book fetch failed: {e}"

    # Require a CLOB ask when live book was requested (normal path)
    if fetch_live_book and signal.get("book_source") != "clob":
        return None, "no live CLOB quote"

    entry = signal["entry_price"]
    if entry <= 0 or entry >= 1:
        return None, "invalid entry price"
    if signal["ev"] < MIN_EV:
        return None, f"EV {signal['ev']:+.4f} < min {MIN_EV}"
    if entry >= MAX_PRICE:
        return None, (
            f"ask ${entry:.3f} >= max_price {MAX_PRICE}"
        )

    risk_skip = risk_limit_reason(
        city_slug, date_str, signal["cost"], balance, book
    )
    if risk_skip:
        return None, f"risk: {risk_skip}"

    return signal, None


def _fmt_bucket(t_low, t_high, unit_sym):
    if t_low == -999:
        return f"≤{t_high}{unit_sym}"
    if t_high == 999:
        return f"≥{t_low}{unit_sym}"
    if t_low == t_high:
        return f"{t_low}{unit_sym}"
    return f"{t_low}-{t_high}{unit_sym}"


def _fmt_temp(val, unit_sym):
    if val is None:
        return "—"
    return f"{val}{unit_sym}"


def scan_preview():
    """
    Dry-run scan: fetch forecasts + markets, report findings and would-be
    entries. Does not open/close positions, resolve, write market files, or
    change balance.
    """
    global _cal
    now = datetime.now(timezone.utc)
    state = load_state()
    balance = state["balance"]
    # Virtual book for risk-cap preview only (not persisted)
    book = portfolio_snapshot(load_all_markets())

    found = 0
    would_buys = []
    skip_counts = {}

    print(f"  Paper balance (unchanged): ${balance:,.2f}")
    print(f"  Open positions (book):     {book['total']} | "
          f"capital at risk ${book['capital']:,.2f}")
    print(f"  Filters: min_ev={MIN_EV} max_price={MAX_PRICE} "
          f"min_vol={MIN_VOLUME} hours=[{MIN_HOURS},{MAX_HOURS}] "
          f"max_bet=${MAX_BET} max_slip={MAX_SLIPPAGE}")
    print()

    for city_slug, loc in LOCATIONS.items():
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']} ({loc['station']})...", flush=True)

        try:
            dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d")
                     for i in range(4)]
            snapshots = take_forecast_snapshot(city_slug, dates)
            time.sleep(0.3)
        except Exception as e:
            print(f"     skipped ({e})")
            continue

        city_hits = 0
        for i, date in enumerate(dates):
            dt = datetime.strptime(date, "%Y-%m-%d")
            event = get_polymarket_event(
                city_slug, MONTHS[dt.month - 1], dt.day, dt.year)
            if not event:
                continue

            end_date = event.get("endDate", "")
            hours = hours_to_resolution(end_date) if end_date else 0
            horizon = f"D+{i}"
            outcomes = parse_event_outcomes(event)
            snap = snapshots.get(date, {})
            forecast_temp = snap.get("best")
            best_source = snap.get("best_source")

            found += 1
            city_hits += 1

            # Read-only look at existing paper state
            mkt = load_market(city_slug, date)
            pos = (mkt or {}).get("position")
            pos_status = (pos or {}).get("status")

            src = (best_source or "?").upper()
            fc_bits = (
                f"best {_fmt_temp(forecast_temp, unit_sym)} ({src})"
                f" | ECMWF {_fmt_temp(snap.get('ecmwf'), unit_sym)}"
                f" HRRR {_fmt_temp(snap.get('hrrr'), unit_sym)}"
                f" METAR {_fmt_temp(snap.get('metar'), unit_sym)}"
            )
            print(f"     {horizon} {date} | {hours:.1f}h left | {fc_bits}")
            print(f"       buckets: {len(outcomes)} | "
                  f"event end {end_date or '—'}")

            # Matched bucket info (even if we will not trade)
            matched = None
            if forecast_temp is not None:
                for o in outcomes:
                    if in_bucket(forecast_temp, o["range"][0], o["range"][1]):
                        matched = o
                        break
            if matched:
                t_low, t_high = matched["range"]
                yes_p = matched.get("yes_price", matched.get("bid"))
                no_p = matched.get("no_price", matched.get("ask"))
                print(
                    f"       match {_fmt_bucket(t_low, t_high, unit_sym)} | "
                    f"yes ${yes_p:.3f} no ${no_p:.3f} "
                    f"(outcomePrices, not CLOB) | "
                    f"vol {matched['volume']:.0f}"
                )
            else:
                print("       match — (forecast not in any bucket)")

            if mkt and mkt.get("status") == "resolved":
                print("       [HOLD] market already resolved on disk")
                skip_counts["resolved"] = skip_counts.get("resolved", 0) + 1
                continue
            if pos_status == "open":
                pl = pos.get("bucket_low")
                ph = pos.get("bucket_high")
                print(
                    f"       [HOLD] open paper pos "
                    f"{_fmt_bucket(pl, ph, unit_sym)} @ "
                    f"${pos.get('entry_price', 0):.3f} "
                    f"(${pos.get('cost', 0):.2f})"
                )
                skip_counts["already_open"] = skip_counts.get(
                    "already_open", 0) + 1
                continue
            if pos is not None:
                print(
                    f"       [HOLD] prior position on file "
                    f"(status={pos_status}) — no re-entry"
                )
                skip_counts["prior_position"] = skip_counts.get(
                    "prior_position", 0) + 1
                continue

            signal, reason = consider_entry(
                city_slug,
                date,
                outcomes,
                forecast_temp,
                best_source,
                hours,
                balance,
                book,
                opened_at=snap.get("ts"),
                fetch_live_book=True,
            )
            if signal:
                bucket_label = _fmt_bucket(
                    signal["bucket_low"], signal["bucket_high"], unit_sym)
                spr = signal.get("spread")
                spr_s = f"${spr:.3f}" if spr is not None else "—"
                print(
                    f"       [WOULD BUY] {bucket_label} | "
                    f"CLOB bid ${signal['bid_at_entry']:.3f} "
                    f"ask ${signal['entry_price']:.3f} "
                    f"spr {spr_s} | "
                    f"EV {signal['ev']:+.2f} | p={signal['p']:.2f} | "
                    f"${signal['cost']:.2f} ({signal['shares']} sh) | "
                    f"{(signal['forecast_src'] or '?').upper()}"
                )
                print(
                    f"                paper fill assumes full ${signal['cost']:.2f} "
                    f"at bestAsk (no depth check)"
                )
                would_buys.append({
                    "city": loc["name"],
                    "city_slug": city_slug,
                    "date": date,
                    "horizon": horizon,
                    "hours": round(hours, 1),
                    "bucket": bucket_label,
                    "signal": signal,
                })
                # Virtual fill so later rows respect risk caps / bankroll
                balance -= signal["cost"]
                book_register_open(
                    book, city_slug, date, signal["cost"])
            else:
                print(f"       [SKIP] {reason}")
                key = reason.split(":")[0].split("<")[0].strip()
                if len(key) > 40:
                    key = key[:40]
                skip_counts[key] = skip_counts.get(key, 0) + 1

            time.sleep(0.1)

        if city_hits == 0:
            print("     (no Polymarket events in next 4 days)")

    # --- Summary ---
    print(f"\n{'='*55}")
    print(f"  SCAN PREVIEW SUMMARY (dry-run — nothing filled)")
    print(f"{'='*55}")
    print(f"  Markets found:     {found}")
    print(f"  Would open:        {len(would_buys)}")
    if skip_counts:
        print(f"  Skip breakdown:")
        for k, n in sorted(skip_counts.items(), key=lambda x: -x[1]):
            print(f"    {n:3d}  {k}")

    if would_buys:
        total_cost = sum(w["signal"]["cost"] for w in would_buys)
        print(f"\n  Hypothetical new positions (${total_cost:.2f} total):")
        for w in would_buys:
            s = w["signal"]
            print(
                f"    {w['city']:<16} {w['horizon']} {w['date']} | "
                f"{w['bucket']:<12} | ${s['entry_price']:.3f} | "
                f"EV {s['ev']:+.2f} | ${s['cost']:.2f} | "
                f"{(s['forecast_src'] or '?').upper()}"
            )
        print(
            f"\n  Virtual balance after would-buys: ${balance:,.2f} "
            f"(not saved)"
        )
    else:
        print("\n  No new positions would be opened under current filters.")

    print(f"{'='*55}\n")
    return found, len(would_buys)


def scan_and_update():
    """Main function of one cycle: updates forecasts, opens/closes positions."""
    global _cal
    now = datetime.now(timezone.utc)
    state = load_state()
    balance = state["balance"]
    new_pos = 0
    closed = 0
    resolved = 0
    # Live portfolio book for risk caps (updated as we open/close in this scan)
    book = portfolio_snapshot(load_all_markets())

    for city_slug, loc in LOCATIONS.items():
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']}...", end=" ", flush=True)

        try:
            dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d")
                     for i in range(4)]
            snapshots = take_forecast_snapshot(city_slug, dates)
            time.sleep(0.3)
        except Exception as e:
            print(f"skipped ({e})")
            continue

        for i, date in enumerate(dates):
            dt = datetime.strptime(date, "%Y-%m-%d")
            event = get_polymarket_event(
                city_slug, MONTHS[dt.month - 1], dt.day, dt.year)
            if not event:
                continue

            end_date = event.get("endDate", "")
            hours = hours_to_resolution(end_date) if end_date else 0
            horizon = f"D+{i}"

            # Load or create market record
            mkt = load_market(city_slug, date)
            if mkt is None:
                if hours < MIN_HOURS or hours > MAX_HOURS:
                    continue
                mkt = new_market(city_slug, date, event, hours)

            # Skip if market already resolved
            if mkt["status"] == "resolved":
                continue

            # Update outcomes list — prices taken directly from event
            outcomes = parse_event_outcomes(event)
            mkt["all_outcomes"] = outcomes

            # Forecast snapshot
            snap = snapshots.get(date, {})
            forecast_snap = {
                "ts":          snap.get("ts"),
                "horizon":     horizon,
                "hours_left":  round(hours, 1),
                "ecmwf":       snap.get("ecmwf"),
                "hrrr":        snap.get("hrrr"),
                "metar":       snap.get("metar"),
                "best":        snap.get("best"),
                "best_source": snap.get("best_source"),
            }
            mkt["forecast_snapshots"].append(forecast_snap)

            # Market price snapshot
            top = max(outcomes, key=lambda x: x["price"]) if outcomes else None
            market_snap = {
                "ts":       snap.get("ts"),
                "top_bucket": f"{top['range'][0]}-{top['range'][1]}{unit_sym}" if top else None,
                "top_price":  top["price"] if top else None,
            }
            mkt["market_snapshots"].append(market_snap)

            forecast_temp = snap.get("best")
            best_source = snap.get("best_source")

            # --- STOP-LOSS AND TRAILING STOP ---
            if mkt.get("position") and mkt["position"].get("status") == "open":
                pos = mkt["position"]
                current_price = None
                for o in outcomes:
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

                if current_price is not None:
                    current_price = o.get("bid", current_price)  # sell at bid
                    entry = pos["entry_price"]
                    # 20% stop by default
                    stop = pos.get("stop_price", entry * 0.80)

                    # Trailing: if up 20%+ — move stop to breakeven
                    if current_price >= entry * 1.20 and stop < entry:
                        pos["stop_price"] = entry
                        pos["trailing_activated"] = True

                    # Check stop
                    if current_price <= stop:
                        pnl = round((current_price - entry) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        book_register_close(book, city_slug, date, pos["cost"])
                        pos["closed_at"] = snap.get("ts")
                        pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
                        pos["exit_price"] = current_price
                        pos["pnl"] = pnl
                        pos["status"] = "closed"
                        closed += 1
                        reason = "STOP" if current_price < entry else "TRAILING BE"
                        print(
                            f"  [{reason}] {loc['name']} {date} | entry ${entry:.3f} exit ${current_price:.3f} | PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")

            # --- CLOSE POSITION if forecast shifted 2+ degrees ---
            # Must require status=="open". Without it, every later scan re-credits
            # cost+pnl for already-closed positions (state.json balance inflation).
            if mkt.get("position") and mkt["position"].get("status") == "open" and forecast_temp is not None:
                pos = mkt["position"]
                old_bucket_low = pos["bucket_low"]
                old_bucket_high = pos["bucket_high"]
                # 2-degree buffer — avoid closing on small forecast fluctuations
                unit = loc["unit"]
                buffer = 2.0 if unit == "F" else 1.0
                mid_bucket = (old_bucket_low + old_bucket_high) / 2 if old_bucket_low != - \
                    999 and old_bucket_high != 999 else forecast_temp
                forecast_far = abs(
                    forecast_temp - mid_bucket) > (abs(mid_bucket - old_bucket_low) + buffer)
                if not in_bucket(forecast_temp, old_bucket_low, old_bucket_high) and forecast_far:
                    current_price = None
                    for o in outcomes:
                        if o["market_id"] == pos["market_id"]:
                            current_price = o["price"]
                            break
                    if current_price is not None:
                        pnl = round(
                            (current_price - pos["entry_price"]) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        book_register_close(book, city_slug, date, pos["cost"])
                        mkt["position"]["closed_at"] = snap.get("ts")
                        mkt["position"]["close_reason"] = "forecast_changed"
                        mkt["position"]["exit_price"] = current_price
                        mkt["position"]["pnl"] = pnl
                        mkt["position"]["status"] = "closed"
                        closed += 1
                        print(
                            f"  [CLOSE] {loc['name']} {date} — forecast changed | PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")

            # --- OPEN POSITION ---
            # One position per market record (closed position blocks re-entry).
            if not mkt.get("position") and forecast_temp is not None and hours >= MIN_HOURS:
                best_signal, skip_reason = consider_entry(
                    city_slug,
                    date,
                    outcomes,
                    forecast_temp,
                    best_source,
                    hours,
                    balance,
                    book,
                    opened_at=snap.get("ts"),
                    fetch_live_book=True,
                )
                if best_signal:
                    balance -= best_signal["cost"]
                    book_register_open(
                        book, city_slug, date, best_signal["cost"])
                    mkt["position"] = best_signal
                    state["total_trades"] += 1
                    new_pos += 1
                    bucket_label = _fmt_bucket(
                        best_signal["bucket_low"],
                        best_signal["bucket_high"],
                        unit_sym,
                    )
                    src = (best_signal["forecast_src"] or "?").upper()
                    print(f"  [BUY]  {loc['name']} {horizon} {date} | {bucket_label} | "
                          f"${best_signal['entry_price']:.3f} | EV {best_signal['ev']:+.2f} | "
                          f"${best_signal['cost']:.2f} ({src})")
                elif skip_reason:
                    if skip_reason.startswith("risk:"):
                        print(
                            f"  [RISK] {loc['name']} {date} — skip: "
                            f"{skip_reason[len('risk:'):].strip()}")
                    elif skip_reason.startswith("real ask") or skip_reason.startswith("ask $"):
                        print(
                            f"  [SKIP] {loc['name']} {date} — {skip_reason}")

            # Market closed by time
            if hours < 0.5 and mkt["status"] == "open":
                mkt["status"] = "closed"

            save_market(mkt)
            time.sleep(0.1)

        print("ok")

    # --- RESOLUTION + ACTUALS ---
    # 1) Open positions held to Polymarket close → settle bankroll + outcome
    # 2) Early-exited positions → still record resolved_outcome (counterfactual
    #    "did our bucket win?") without touching balance
    # 3) Past dates → backfill station actual_temp for residual calibration
    today_str = now.strftime("%Y-%m-%d")
    outcome_backfill = 0

    for mkt in load_all_markets():
        pos = mkt.get("position")
        market_id = (pos or {}).get("market_id")
        dirty = False

        # --- Polymarket bucket outcome ---
        if market_id and mkt.get("resolved_outcome") is None:
            won = check_market_resolved(market_id)
            if won is not None:
                mkt["resolved_outcome"] = "win" if won else "loss"
                mkt["resolved"] = True
                mkt["status"] = "resolved"
                dirty = True

                price = pos["entry_price"]
                size = pos["cost"]
                shares = pos["shares"]
                hold_pnl = round(
                    shares * (1 - price), 2) if won else round(-size, 2)
                # What PnL would have been if held to $0/$1 resolution
                mkt["hold_to_resolution_pnl"] = hold_pnl

                if pos.get("status") == "open":
                    # Still open at settlement → credit bankroll
                    balance += size + hold_pnl
                    book_register_close(book, mkt["city"], mkt["date"], size)
                    pos["exit_price"] = 1.0 if won else 0.0
                    pos["pnl"] = hold_pnl
                    pos["close_reason"] = "resolved"
                    pos["closed_at"] = now.isoformat()
                    pos["status"] = "closed"
                    mkt["pnl"] = hold_pnl
                    mkt["held_to_resolution"] = True
                    if won:
                        state["wins"] += 1
                    else:
                        state["losses"] += 1
                    result = "WIN" if won else "LOSS"
                    print(
                        f"  [{result}] {mkt['city_name']} {mkt['date']} | "
                        f"held | PnL: {'+' if hold_pnl >= 0 else ''}{hold_pnl:.2f}")
                    resolved += 1
                else:
                    # Already exited (TP/stop/forecast) — annotate only
                    mkt["held_to_resolution"] = False
                    exit_pnl = pos.get("pnl")
                    exit_str = (
                        f"exit PnL {'+' if exit_pnl >= 0 else ''}{exit_pnl:.2f}"
                        if exit_pnl is not None else "exit PnL n/a"
                    )
                    result = "BUCKET WIN" if won else "BUCKET LOSS"
                    print(
                        f"  [{result}] {mkt['city_name']} {mkt['date']} | "
                        f"exited early ({pos.get('close_reason')}) | "
                        f"{exit_str} | hold would be "
                        f"{'+' if hold_pnl >= 0 else ''}{hold_pnl:.2f}")
                    outcome_backfill += 1

                time.sleep(0.3)

        # --- Station actual (residuals), once the calendar day is past ---
        if mkt.get("actual_temp") is None and mkt.get("date", today_str) < today_str:
            actual = get_actual_temp(mkt["city"], mkt["date"])
            if actual is not None:
                mkt["actual_temp"] = actual
                mkt["resolved"] = True
                dirty = True
                time.sleep(0.2)

        if dirty:
            save_market(mkt)

    if outcome_backfill:
        print(f"  [SETTLE] annotated {outcome_backfill} early-exit market outcome(s)")

    state["balance"] = round(balance, 2)
    state["peak_balance"] = max(state.get("peak_balance", balance), balance)
    # Persist cash + rebuild trade KPIs from market files (source of truth)
    all_mkts = load_all_markets()
    refresh_state_stats(state=state, markets=all_mkts, write=True)

    # Run calibration when enough markets have actuals
    cal_eligible = len([
        m for m in all_mkts
        if m.get("actual_temp") is not None
        and (m.get("status") == "resolved" or m.get("resolved"))
    ])
    if cal_eligible >= CALIBRATION_MIN:
        _cal = run_calibration(all_mkts)

    return new_pos, closed, resolved

# =============================================================================
# REPORT
# =============================================================================


def print_status():
    state = load_state()
    markets = load_all_markets()
    # Rebuild summary KPIs from markets; keep cash fields as stored
    state = refresh_state_stats(state=state, markets=markets, write=True)

    open_pos = [m for m in markets if m.get(
        "position") and m["position"].get("status") == "open"]

    bal = state["balance"]
    start = state["starting_balance"]
    peak = state.get("peak_balance", bal)
    equity = state.get("equity", bal)
    ret_pct = state.get("return_pct", 0.0)
    dd_pct = state.get("drawdown_pct", 0.0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    held_n = wins + losses
    closed_n = state.get("closed_count", 0)
    open_n = state.get("open_count", 0)
    realized = state.get("realized_pnl", 0.0)
    exits = state.get("exits") or {}
    buckets = state.get("bucket_outcomes") or {}
    hv = state.get("hold_vs_exit") or {}

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STATUS")
    print(f"{'='*55}")
    print(
        f"  Cash:        ${bal:,.2f}  (start ${start:,.2f}, peak ${peak:,.2f})")
    print(
        f"  Equity:      ${equity:,.2f}  (cash + ${state.get('open_capital', 0):,.2f} open)  "
        f"{'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%  DD {dd_pct:.2f}%")
    recon = reconcile_balance(apply=False, markets=markets, state=state)
    if not recon["ok"]:
        print(
            f"  Balance check: DRIFT ${recon['delta']:+,.2f} vs market files "
            f"(true ${recon['true_balance']:,.2f}) — run: python weatherbet.py reconcile --fix")
    print(
        f"  Realized:    {'+' if realized >= 0 else ''}{realized:.2f}  "
        f"on {closed_n} closed | open {open_n} | total {state.get('total_trades', 0)}")
    if held_n:
        print(
            f"  Held→resolve: W {wins} / L {losses}  WR {wins/held_n:.0%}")
    else:
        print(f"  Held→resolve: none yet (wins/losses only count full holds)")
    bw, bl, bp = buckets.get("win", 0), buckets.get("loss", 0), buckets.get("pending", 0)
    print(f"  Bucket out:  win {bw} / loss {bl} / pending {bp}  "
          f"(includes early exits once annotated)")
    if exits:
        parts = [
            f"{r} {v['n']} ({'+' if v['pnl'] >= 0 else ''}{v['pnl']:.2f})"
            for r, v in sorted(exits.items(), key=lambda x: -x[1]["n"])
        ]
        print(f"  Exits:       {', '.join(parts)}")
    if hv.get("annotated"):
        d = hv.get("hold_minus_exit", 0)
        print(
            f"  Hold vs exit: n={hv['annotated']}  exit {hv.get('exit_pnl_sum', 0):+.2f}  "
            f"hold {hv.get('hold_pnl_sum', 0):+.2f}  "
            f"Δhold-exit {d:+.2f}  ({'hold better' if d > 0 else 'exit better' if d < 0 else 'flat'})")
    print(f"  Actuals:     {state.get('actuals_count', 0)} markets with station temp")

    if open_pos:
        print(f"\n  Open positions:")
        total_unrealized = 0.0
        for m in open_pos:
            pos = m["position"]
            unit_sym = "F" if m["unit"] == "F" else "C"
            label = f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}"

            # Current price from latest market snapshot
            current_price = pos["entry_price"]
            snaps = m.get("market_snapshots", [])
            if snaps:
                # Find our bucket price in all_outcomes
                for o in m.get("all_outcomes", []):
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

            unrealized = round(
                (current_price - pos["entry_price"]) * pos["shares"], 2)
            total_unrealized += unrealized
            pnl_str = f"{'+'if unrealized >= 0 else ''}{unrealized:.2f}"

            print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | "
                  f"entry ${pos['entry_price']:.3f} -> ${current_price:.3f} | "
                  f"PnL: {pnl_str} | {pos['forecast_src'].upper()}")

        sign = "+" if total_unrealized >= 0 else ""
        print(f"\n  Unrealized PnL: {sign}{total_unrealized:.2f}")

    print(f"{'='*55}\n")


def print_report():
    markets = load_all_markets()
    resolved = [m for m in markets if m["status"]
                == "resolved" and m.get("pnl") is not None]

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — FULL REPORT")
    print(f"{'='*55}")

    if not resolved:
        print("  No resolved markets yet.")
        return

    total_pnl = sum(m["pnl"] for m in resolved)
    wins = [m for m in resolved if m["resolved_outcome"] == "win"]
    losses = [m for m in resolved if m["resolved_outcome"] == "loss"]

    print(f"\n  Total resolved: {len(resolved)}")
    print(f"  Wins:           {len(wins)} | Losses: {len(losses)}")
    print(f"  Win rate:       {len(wins)/len(resolved):.0%}")
    print(f"  Total PnL:      {'+'if total_pnl >= 0 else ''}{total_pnl:.2f}")

    print(f"\n  By city:")
    for city in sorted(set(m["city"] for m in resolved)):
        group = [m for m in resolved if m["city"] == city]
        w = len([m for m in group if m["resolved_outcome"] == "win"])
        pnl = sum(m["pnl"] for m in group)
        name = LOCATIONS[city]["name"]
        print(
            f"    {name:<16} {w}/{len(group)} ({w/len(group):.0%})  PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")

    print(f"\n  Market details:")
    for m in sorted(resolved, key=lambda x: x["date"]):
        pos = m.get("position", {})
        unit_sym = "F" if m["unit"] == "F" else "C"
        snaps = m.get("forecast_snapshots", [])
        first_fc = snaps[0]["best"] if snaps else None
        last_fc = snaps[-1]["best"] if snaps else None
        label = f"{pos.get('bucket_low')}-{pos.get('bucket_high')}{unit_sym}" if pos else "no position"
        result = m["resolved_outcome"].upper()
        pnl_str = f"{'+'if m['pnl'] >= 0 else ''}{m['pnl']:.2f}" if m["pnl"] is not None else "-"
        fc_str = f"forecast {first_fc}->{last_fc}{unit_sym}" if first_fc else "no forecast"
        actual = f"actual {m['actual_temp']}{unit_sym}" if m["actual_temp"] else ""
        print(
            f"    {m['city_name']:<16} {m['date']} | {label:<14} | {fc_str} | {actual} | {result} {pnl_str}")

    print(f"{'='*55}\n")

# =============================================================================
# MAIN LOOP
# =============================================================================


MONITOR_INTERVAL = 600  # monitor positions every 10 minutes


def monitor_positions():
    """Quick stop check on open positions without full scan."""
    markets = load_all_markets()
    open_pos = [m for m in markets if m.get(
        "position") and m["position"].get("status") == "open"]
    if not open_pos:
        return 0

    state = load_state()
    balance = state["balance"]
    closed = 0

    for mkt in open_pos:
        pos = mkt["position"]
        mid = pos["market_id"]

        # Fetch real bestBid from Polymarket API — actual sell price
        current_price = None
        try:
            r = requests.get(
                f"https://gamma-api.polymarket.com/markets/{mid}", timeout=(3, 5))
            mdata = r.json()
            best_bid = mdata.get("bestBid")
            if best_bid is not None:
                current_price = float(best_bid)
        except Exception:
            pass

        # Fallback to cached price if API failed
        if current_price is None:
            for o in mkt.get("all_outcomes", []):
                if o["market_id"] == mid:
                    current_price = o.get("bid", o["price"])
                    break

        if current_price is None:
            continue

        entry = pos["entry_price"]
        stop = pos.get("stop_price", entry * 0.80)
        city_name = LOCATIONS.get(mkt["city"], {}).get("name", mkt["city"])

        # Hours left to resolution
        end_date = mkt.get("event_end_date", "")
        hours_left = hours_to_resolution(end_date) if end_date else 999.0

        # Take-profit threshold based on hours to resolution
        if hours_left < 24:
            take_profit = None        # hold to resolution
        elif hours_left < 48:
            take_profit = 0.85        # 24-48h: take profit at $0.85
        else:
            take_profit = 0.75        # 48h+: take profit at $0.75

        # Trailing: if up 20%+ — move stop to breakeven
        if current_price >= entry * 1.20 and stop < entry:
            pos["stop_price"] = entry
            pos["trailing_activated"] = True
            print(
                f"  [TRAILING] {city_name} {mkt['date']} — stop moved to breakeven ${entry:.3f}")

        # Check take-profit
        take_triggered = take_profit is not None and current_price >= take_profit
        # Check stop
        stop_triggered = current_price <= stop

        if take_triggered or stop_triggered:
            pnl = round((current_price - entry) * pos["shares"], 2)
            balance += pos["cost"] + pnl
            pos["closed_at"] = datetime.now(timezone.utc).isoformat()
            if take_triggered:
                pos["close_reason"] = "take_profit"
                reason = "TAKE"
            elif current_price < entry:
                pos["close_reason"] = "stop_loss"
                reason = "STOP"
            else:
                pos["close_reason"] = "trailing_stop"
                reason = "TRAILING BE"
            pos["exit_price"] = current_price
            pos["pnl"] = pnl
            pos["status"] = "closed"
            closed += 1
            print(f"  [{reason}] {city_name} {mkt['date']} | entry ${entry:.3f} exit ${current_price:.3f} | {hours_left:.0f}h left | PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")
            save_market(mkt)

    if closed:
        state["balance"] = round(balance, 2)
        refresh_state_stats(state=state, markets=load_all_markets(), write=True)

    return closed


def run_loop():
    global _cal
    _cal = load_cal()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STARTING")
    print(f"{'='*55}")
    print(f"  Cities:     {len(LOCATIONS)}")
    print(f"  Balance:    ${BALANCE:,.0f} | Max bet: ${MAX_BET}")
    print(f"  Risk:       open≤{MAX_OPEN_POSITIONS} | "
          f"city≤{MAX_OPEN_PER_CITY} | date≤{MAX_OPEN_PER_DATE} | "
          f"capital≤{MAX_CAPITAL_AT_RISK_PCT:.0%}")
    print(
        f"  Scan:       {SCAN_INTERVAL//60} min | Monitor: {MONITOR_INTERVAL//60} min")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0)")
    print(f"  Data:       {DATA_DIR.resolve()}")
    print(f"  Ctrl+C to stop\n")

    last_full_scan = 0

    while True:
        now_ts = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Full scan once per hour
        if now_ts - last_full_scan >= SCAN_INTERVAL:
            print(f"[{now_str}] full scan...")
            try:
                new_pos, closed, resolved = scan_and_update()
                state = load_state()
                print(f"  balance: ${state['balance']:,.2f} | "
                      f"new: {new_pos} | closed: {closed} | resolved: {resolved}")
                last_full_scan = time.time()
            except KeyboardInterrupt:
                print(f"\n  Stopping — saving state...")
                save_state(load_state())
                print(f"  Done. Bye!")
                break
            except requests.exceptions.ConnectionError:
                print(f"  Connection lost — waiting 60 sec")
                time.sleep(60)
                continue
            except Exception as e:
                print(f"  Error: {e} — waiting 60 sec")
                time.sleep(60)
                continue
        else:
            # Quick stop monitoring
            print(f"[{now_str}] monitoring positions...")
            try:
                stopped = monitor_positions()
                if stopped:
                    state = load_state()
                    print(f"  balance: ${state['balance']:,.2f}")
            except Exception as e:
                print(f"  Monitor error: {e}")

        try:
            time.sleep(MONITOR_INTERVAL)
        except KeyboardInterrupt:
            print(f"\n  Stopping — saving state...")
            save_state(load_state())
            print(f"  Done. Bye!")
            break

# =============================================================================
# CLI
# =============================================================================


def run_scan_once():
    """
    Dry-run scan: show markets found and positions that *would* open.
    Does not fill, resolve, or write state/market files.
    """
    global _cal
    _cal = load_cal()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — SCAN PREVIEW (dry-run)")
    print(f"{'='*55}")
    print(f"  Cities:     {len(LOCATIONS)}")
    print(f"  Balance:    ${load_state()['balance']:,.2f} | Max bet: ${MAX_BET}")
    print(f"  Risk:       open≤{MAX_OPEN_POSITIONS} | "
          f"city≤{MAX_OPEN_PER_CITY} | date≤{MAX_OPEN_PER_DATE} | "
          f"capital≤{MAX_CAPITAL_AT_RISK_PCT:.0%}")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0)")
    print(f"  Mode:       read-only — no paper fills, no disk writes")
    print(f"  Data:       {DATA_DIR.resolve()} (read for open book only)\n")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] preview scan...")
    try:
        found, would = scan_preview()
        print(f"  Done. Found {found} market(s); would open {would}.\n")
    except KeyboardInterrupt:
        print(f"\n  Interrupted — no changes written.")
        raise SystemExit(130)
    except requests.exceptions.ConnectionError:
        print(f"  Connection lost during scan.")
        raise SystemExit(1)
    except Exception as e:
        print(f"  Error: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run_loop()
    elif cmd == "scan":
        run_scan_once()
    elif cmd == "status":
        _cal = load_cal()
        print_status()
    elif cmd == "report":
        _cal = load_cal()
        print_report()
    elif cmd == "reconcile":
        apply = "--fix" in sys.argv[2:]
        print_reconcile(apply=apply)
    elif cmd == "refresh":
        st = refresh_state_stats(write=True)
        print(f"\n  state.json portfolio stats refreshed from market files")
        print(f"  cash ${st['balance']:,.2f} | equity ${st.get('equity', 0):,.2f} | "
              f"realized {st.get('realized_pnl', 0):+.2f} | "
              f"open {st.get('open_count', 0)} closed {st.get('closed_count', 0)}\n")
    else:
        print("Usage: python weatherbet.py [run|scan|status|report|reconcile|refresh]")
