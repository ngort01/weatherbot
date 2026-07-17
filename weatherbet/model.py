"""Probability, EV, and Kelly sizing.

Formulas, worked examples, and binary-p implications: MODEL.md (repo root).
"""
import math

from weatherbet import config
from weatherbet.polymarket import in_bucket


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bucket_prob(forecast, t_low, t_high, sigma=None):
    """Middle bins: binary match. Edge buckets (-999/999): normal CDF. See MODEL.md."""
    s = sigma or 2.0
    if t_low == -999:
        return norm_cdf((t_high - float(forecast)) / s)
    if t_high == 999:
        return 1.0 - norm_cdf((t_low - float(forecast)) / s)
    return 1.0 if in_bucket(forecast, t_low, t_high) else 0.0

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
