"""
Characterization: bucket_prob — *current* semantics (not IMPROVEMENTS target).

Current contract:
- Middle / zero-width bins: binary via in_bucket → p in {0.0, 1.0}; sigma ignored
- Edge bins (-999 / 999): normal CDF with sigma (default 2.0)

Do not change these tests to continuous equal-bound CDF without a product decision.
See IMPROVEMENTS.md §1 (Trap A zero-width, Trap B σ=2 vs market prices).
"""

import weatherbet as wb


# ---------------------------------------------------------------------------
# Middle / range buckets — binary
# ---------------------------------------------------------------------------


def test_middle_bucket_in_returns_one_regardless_of_sigma():
    for sigma in (None, 0.5, 2.0, 10.0):
        assert wb.bucket_prob(46.5, 46, 47, sigma=sigma) == 1.0


def test_middle_bucket_out_returns_zero_regardless_of_sigma():
    for sigma in (None, 0.5, 2.0, 10.0):
        assert wb.bucket_prob(50, 46, 47, sigma=sigma) == 0.0


# ---------------------------------------------------------------------------
# Zero-width — still binary (Trap A: naive continuous would be 0)
# ---------------------------------------------------------------------------


def test_zero_width_match_is_one_not_continuous_zero():
    """Exact 'be 80°F' with matching forecast → p=1.0 under current code."""
    assert wb.bucket_prob(80, 80, 80, sigma=2.0) == 1.0
    assert wb.bucket_prob(80.4, 80, 80, sigma=2.0) == 1.0


def test_zero_width_miss_is_zero():
    assert wb.bucket_prob(81, 80, 80, sigma=2.0) == 0.0


def test_naive_continuous_equal_bounds_would_be_zero_but_we_do_not():
    """Document Trap A: Φ((h-μ)/s)-Φ((l-μ)/s) with l==h is 0; bot is not that."""
    t = 80.0
    continuous = wb.norm_cdf((t - 80.0) / 2.0) - wb.norm_cdf((t - 80.0) / 2.0)
    assert continuous == 0.0
    assert wb.bucket_prob(80, 80, 80, sigma=2.0) == 1.0


# ---------------------------------------------------------------------------
# Edge buckets — CDF
# ---------------------------------------------------------------------------


def test_or_below_edge_uses_cdf():
    # p = Φ((t_high - forecast) / s)
    forecast, t_high, s = 48.0, 50.0, 2.0
    expected = wb.norm_cdf((t_high - forecast) / s)
    assert abs(wb.bucket_prob(forecast, -999, t_high, sigma=s) - expected) < 1e-12


def test_or_higher_edge_uses_cdf():
    # p = 1 - Φ((t_low - forecast) / s)
    forecast, t_low, s = 92.0, 90.0, 2.0
    expected = 1.0 - wb.norm_cdf((t_low - forecast) / s)
    assert abs(wb.bucket_prob(forecast, t_low, 999, sigma=s) - expected) < 1e-12


def test_edge_default_sigma_is_two_when_none():
    forecast, t_high = 50.0, 50.0
    with_default = wb.bucket_prob(forecast, -999, t_high, sigma=None)
    with_two = wb.bucket_prob(forecast, -999, t_high, sigma=2.0)
    assert with_default == with_two


def test_edge_probabilities_in_unit_interval():
    p_lo = wb.bucket_prob(40, -999, 50, sigma=2.0)
    p_hi = wb.bucket_prob(100, 90, 999, sigma=2.0)
    assert 0.0 <= p_lo <= 1.0
    assert 0.0 <= p_hi <= 1.0


def test_or_below_far_below_cap_is_high():
    # Forecast well under the "or below" threshold
    p = wb.bucket_prob(30, -999, 50, sigma=2.0)
    assert p > 0.99


def test_or_higher_far_above_floor_is_high():
    p = wb.bucket_prob(100, 90, 999, sigma=2.0)
    assert p > 0.99


# ---------------------------------------------------------------------------
# Reference only: Trap B numbers (not current bucket_prob output)
# ---------------------------------------------------------------------------


def test_reference_one_degree_mass_under_sigma_two():
    """~19.7% peak mass in 1° window at σ=2 — why continuous would refuse 35¢ modes."""
    half = 0.5
    s = 2.0
    mass = wb.norm_cdf(half / s) - wb.norm_cdf(-half / s)
    assert abs(mass - (2 * wb.norm_cdf(0.25) - 1)) < 1e-12
    assert 0.19 < mass < 0.20
