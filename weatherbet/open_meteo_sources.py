"""
Open-Meteo model registry (data only).

Snapshot key → fetch config. regions=None means global (all cities).
Trading still uses pick_best (HRRR/ECMWF only); extra keys are collected
for calibration and future blending.
"""

HRRR_HORIZON_DAYS = 2

OPEN_METEO_SOURCES = {
    "ecmwf": {
        "model": "ecmwf_ifs025",
        "regions": None,
        "forecast_days": 7,
        "bias_correction": True,
        "tag": "ECMWF",
    },
    # Legacy key "hrrr": NOAA seamless (HRRR near-term + GFS). US only.
    "hrrr": {
        "model": "gfs_seamless",
        "regions": frozenset({"us"}),
        "forecast_days": 3,
        "max_horizon_days": HRRR_HORIZON_DAYS,
        "tag": "HRRR",
    },
    # DWD ICON seamless (global + EU nest where available)
    "icon": {
        "model": "icon_seamless",
        "regions": frozenset({"eu"}),
        "forecast_days": 7,
        "tag": "ICON",
    },
    # Météo-France seamless (ARPEGE/AROME)
    "meteofrance": {
        "model": "meteofrance_seamless",
        "regions": frozenset({"eu"}),
        "forecast_days": 7,
        "tag": "MF",
    },
    # UK Met Office seamless
    "ukmo": {
        "model": "ukmo_seamless",
        "regions": frozenset({"eu"}),
        "forecast_days": 7,
        "tag": "UKMO",
    },
    # Environment Canada GEM seamless
    "gem": {
        "model": "gem_seamless",
        "regions": frozenset({"ca"}),
        "forecast_days": 7,
        "tag": "GEM",
    },
    # Japan JMA seamless
    "jma": {
        "model": "jma_seamless",
        "regions": frozenset({"asia"}),
        "forecast_days": 7,
        "tag": "JMA",
    },
    # Korea KMA seamless (may be empty when model feed is down)
    "kma": {
        "model": "kma_seamless",
        "regions": frozenset({"asia"}),
        "forecast_days": 7,
        "tag": "KMA",
    },
    # China CMA GRAPES global
    "cma": {
        "model": "cma_grapes_global",
        "regions": frozenset({"asia"}),
        "forecast_days": 7,
        "tag": "CMA",
    },
    # Australia BOM ACCESS global (Oceania; may be empty when feed is down)
    "bom": {
        "model": "bom_access_global",
        "regions": frozenset({"oc"}),
        "forecast_days": 7,
        "tag": "BOM",
    },
}

# Stable order for logs / calibration (Open-Meteo keys + observation).
FORECAST_SOURCE_KEYS = tuple(OPEN_METEO_SOURCES.keys()) + ("metar",)
