"""Config, paths, locations — loaded at import from cwd config.json + .env."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

with open("config.json", encoding="utf-8") as f:
    _cfg = json.load(f)

BALANCE = _cfg.get("balance", 10000.0)
MAX_BET = _cfg.get("max_bet", 20.0)
MIN_EV = _cfg.get("min_ev", 0.10)
MAX_PRICE = _cfg.get("max_price", 0.45)
MIN_PRICE = float(_cfg.get("min_price", 0.08))
MIN_VOLUME = _cfg.get("min_volume", 500)
MIN_HOURS = _cfg.get("min_hours", 2.0)
MAX_HOURS = _cfg.get("max_hours", 72.0)
KELLY_FRACTION = _cfg.get("kelly_fraction", 0.25)
MAX_SLIPPAGE = _cfg.get("max_slippage", 0.03)
# When Gamma reports liquidity (USD), require at least this (and >= cost). 0 = off.
MIN_ASK_DEPTH_USD = float(_cfg.get("min_ask_depth_usd", 25.0))
# Stop: entry - max(entry * stop_loss_pct, min_stop_width)
STOP_LOSS_PCT = float(_cfg.get("stop_loss_pct", 0.20))
MIN_STOP_WIDTH = float(_cfg.get("min_stop_width", 0.05))
SCAN_INTERVAL = _cfg.get("scan_interval", 3600)
CALIBRATION_MIN = _cfg.get("calibration_min", 30)
MAX_OPEN_POSITIONS = int(_cfg.get("max_open_positions", 20))
MAX_OPEN_PER_CITY = int(_cfg.get("max_open_per_city", 2))
MAX_OPEN_PER_DATE = int(_cfg.get("max_open_per_date", 6))
MAX_CAPITAL_AT_RISK_PCT = float(_cfg.get("max_capital_at_risk_pct", 0.2))
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

MONITOR_INTERVAL = 600  # monitor positions every 10 minutes
