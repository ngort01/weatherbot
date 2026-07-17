"""
WeatherBet — paper-trading bot for Polymarket highest-temperature markets.

Public API mirrors the former monolithic weatherbet.py module so tests and
scripts can `import weatherbet as wb`.
"""
from weatherbet.config import (  # noqa: F401
    BALANCE, MAX_BET, MIN_EV, MAX_PRICE, MIN_VOLUME, MIN_HOURS, MAX_HOURS,
    KELLY_FRACTION, MAX_SLIPPAGE, SCAN_INTERVAL, CALIBRATION_MIN,
    MAX_OPEN_POSITIONS, MAX_OPEN_PER_CITY, MAX_OPEN_PER_DATE,
    MAX_CAPITAL_AT_RISK_PCT, VC_KEY, SIGMA_F, SIGMA_C,
    DATA_DIR, STATE_FILE, MARKETS_DIR, CALIBRATION_FILE,
    LOCATIONS, TIMEZONES, MONTHS, MONITOR_INTERVAL,
)
from weatherbet.model import (  # noqa: F401
    norm_cdf, resolution_bin, bucket_prob, event_bucket_probs,
    calc_ev, calc_kelly, bet_size,
)
from weatherbet.polymarket import (  # noqa: F401
    parse_temp_range, hours_to_resolution, in_bucket,
    get_polymarket_event, get_market_price, check_market_resolved,
    parse_event_outcomes,
)
from weatherbet.forecasts import (  # noqa: F401
    get_ecmwf, get_hrrr, get_metar, get_actual_temp, take_forecast_snapshot,
)
from weatherbet.calibration import (  # noqa: F401
    load_cal, get_sigma, get_bias, snapshot_source_temp, run_calibration, _cal,
)
from weatherbet.storage import (  # noqa: F401
    market_path, load_market, save_market, load_all_markets, new_market,
)
from weatherbet.risk import (  # noqa: F401
    portfolio_snapshot, risk_limit_reason, book_register_open, book_register_close,
)
from weatherbet.state import (  # noqa: F401
    default_state, load_state, save_state, balance_from_markets,
    compute_portfolio_stats, refresh_state_stats, reconcile_balance,
    print_reconcile,
)
from weatherbet.entry import consider_entry, _fmt_bucket, _fmt_temp  # noqa: F401
from weatherbet.scan import scan_preview, scan_and_update  # noqa: F401
from weatherbet.monitor import monitor_positions  # noqa: F401
from weatherbet.report import print_status, print_report  # noqa: F401
from weatherbet.cli import run_loop, run_scan_once, main  # noqa: F401
