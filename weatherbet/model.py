"""Probability, EV, and Kelly sizing.

Formulas, worked examples, and partition-model implications: MODEL.md (repo root).
"""
import math

from weatherbet import config


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def resolution_bin(t_low, t_high):
    """
    Map a parsed Polymarket temp range to continuous support for integer-degree
    resolution. Adjacent market buckets form a partition of R.

    Exact `be v`     → [v-0.5, v+0.5)
    Between a–b      → [a-0.5, b+0.5)
    Or below T       → (-inf, T+0.5)
    Or higher T      → [T-0.5, +inf)
    """
    if t_low == -999:
        return (-math.inf, float(t_high) + 0.5)
    if t_high == 999:
        return (float(t_low) - 0.5, math.inf)
    if t_low == t_high:
        v = float(t_low)
        return (v - 0.5, v + 0.5)
    return (float(t_low) - 0.5, float(t_high) + 0.5)


def bucket_prob(forecast, t_low, t_high, sigma=None, bias=0.0):
    """
    P(resolution high falls in bucket) under N(μ, σ²).

    μ = forecast − bias (bias = mean(forecast − actual) from calibration).
    Support is resolution_bin(t_low, t_high) — half-degree edges so exact bins
    have positive mass. See MODEL.md.

    Default σ when omitted is config.SIGMA_F only (unit-agnostic pure helper).
    Callers for °C cities must pass σ explicitly — use calibration.get_sigma
    (returns SIGMA_C or calibrated value). Entry always does this.
    """
    s = float(sigma if sigma is not None else config.SIGMA_F)
    s = max(s, 1e-6)
    mu = float(forecast) - float(bias or 0.0)
    lo, hi = resolution_bin(t_low, t_high)
    z_hi = 1.0 if hi == math.inf else norm_cdf((hi - mu) / s)
    z_lo = 0.0 if lo == -math.inf else norm_cdf((lo - mu) / s)
    return max(0.0, min(1.0, z_hi - z_lo))


def event_bucket_probs(forecast, ranges, sigma=None, bias=0.0, renormalize=True):
    """
    Partition probabilities for a list of (t_low, t_high) ranges.

    When renormalize=True (default), scale so sum ≈ 1 to absorb float edge
    mass outside the listed outcomes.
    """
    raw = [bucket_prob(forecast, lo, hi, sigma, bias) for lo, hi in ranges]
    total = sum(raw)
    if renormalize and total > 0:
        return [p / total for p in raw]
    return raw


def calc_ev(p, price):
    """YES expected value at `price`. See MODEL.md."""
    if price <= 0 or price >= 1:
        return 0.0
    return round(p * (1.0 / price - 1.0) - (1.0 - p), 4)


def calc_kelly(p, price):
    """Fractional Kelly fraction of bankroll (× kelly_fraction, capped). See MODEL.md."""
    if price <= 0 or price >= 1:
        return 0.0
    b = 1.0 / price - 1.0
    f = (p * b - (1.0 - p)) / b
    return round(min(max(0.0, f) * config.KELLY_FRACTION, 1.0), 4)


def bet_size(kelly, balance):
    """Dollar stake: kelly × balance, capped at max_bet. See MODEL.md."""
    raw = kelly * balance
    return round(min(raw, config.MAX_BET), 2)


def compute_stop_price(entry, stop_pct=None, min_width=None):
    """
    Initial stop below entry: entry − max(entry × stop_pct, min_width).

    Percentage-only stops (e.g. −20%) leave sub-cent room on cheap books and
    get shaken out by bid noise. min_width enforces a minimum price distance
    (default from config.MIN_STOP_WIDTH). Result is clamped at 0.
    """
    if entry is None:
        return None
    e = float(entry)
    if e <= 0:
        return 0.0
    pct = float(stop_pct if stop_pct is not None else config.STOP_LOSS_PCT)
    floor = float(min_width if min_width is not None else config.MIN_STOP_WIDTH)
    width = max(e * pct, floor)
    return round(max(e - width, 0.0), 4)


def residual_edge(p, bid):
    """
    Model mass on the held bucket minus salvage YES bid.

    Positive → model still values the ticket above what the book pays to exit.
    """
    if p is None or bid is None:
        return None
    return float(p) - float(bid)


def should_exit_on_forecast(p, bid, min_edge=None):
    """
    Forecast-driven exit gate: sell only when residual edge is gone.

    edge = p − bid. Exit when edge ≤ min_edge (default
    config.FORECAST_EXIT_MIN_EDGE, typically 0).

    Price stops remain separate. Missing bid → do not forecast-exit (cannot
    sell). See IMPROVEMENTS §12 / MODEL.md.
    """
    if p is None or bid is None:
        return False
    try:
        b = float(bid)
        prob = float(p)
    except (TypeError, ValueError):
        return False
    if b < 0:
        return False
    floor = float(
        min_edge if min_edge is not None else config.FORECAST_EXIT_MIN_EDGE
    )
    return (prob - b) <= floor
