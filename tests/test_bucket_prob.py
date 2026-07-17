"""
bucket_prob — resolution-aware Gaussian partition (Option B).

- Exact / range / edge buckets use continuous mass over resolution_bin
- Zero-width exact bins get positive measure ([v-0.5, v+0.5))
- Default σ=2 puts ~20% mass on a 1° mode bin (Trap B — intentional)

See MODEL.md and IMPROVEMENTS.md §1.
"""

import math

import weatherbet as wb


# ---------------------------------------------------------------------------
# resolution_bin
# ---------------------------------------------------------------------------


def test_resolution_bin_exact():
    assert wb.resolution_bin(80, 80) == (79.5, 80.5)


def test_resolution_bin_range():
    assert wb.resolution_bin(46, 47) == (45.5, 47.5)


def test_resolution_bin_or_below():
    lo, hi = wb.resolution_bin(-999, 50)
    assert lo == -math.inf
    assert hi == 50.5


def test_resolution_bin_or_higher():
    lo, hi = wb.resolution_bin(90, 999)
    assert lo == 89.5
    assert hi == math.inf


def test_adjacent_bins_abut():
    """Typical event layout: ≤89 | 90-91 | 92-93 | ≥94 — no gaps/overlaps."""
    edges = [
        wb.resolution_bin(-999, 89),
        wb.resolution_bin(90, 91),
        wb.resolution_bin(92, 93),
        wb.resolution_bin(94, 999),
    ]
    for i in range(len(edges) - 1):
        assert edges[i][1] == edges[i + 1][0]


# ---------------------------------------------------------------------------
# Middle / range buckets — continuous mass
# ---------------------------------------------------------------------------


def test_middle_bucket_mode_mass_depends_on_sigma():
    p_tight = wb.bucket_prob(46.5, 46, 47, sigma=0.5)
    p_wide = wb.bucket_prob(46.5, 46, 47, sigma=2.0)
    assert p_tight > p_wide
    assert 0.0 < p_wide < 1.0
    # Range 46–47 → [45.5, 47.5); μ=46.5, σ=2 → Φ(0.5) − Φ(−0.5) ≈ 0.383
    expected = wb.norm_cdf(0.5) - wb.norm_cdf(-0.5)
    assert abs(p_wide - expected) < 1e-12


def test_middle_bucket_far_from_forecast_is_small():
    p = wb.bucket_prob(50, 46, 47, sigma=2.0)
    assert p < 0.12


# ---------------------------------------------------------------------------
# Zero-width — positive mass (Trap A fixed)
# ---------------------------------------------------------------------------


def test_zero_width_match_has_positive_mass():
    """Exact 'be 80°F' is [79.5, 80.5), not p=0 from equal continuous bounds."""
    p = wb.bucket_prob(80, 80, 80, sigma=2.0)
    expected = wb.norm_cdf(0.5 / 2.0) - wb.norm_cdf(-0.5 / 2.0)
    assert abs(p - expected) < 1e-12
    assert 0.19 < p < 0.20


def test_zero_width_miss_is_lower_than_match():
    p_match = wb.bucket_prob(80, 80, 80, sigma=2.0)
    p_miss = wb.bucket_prob(81, 80, 80, sigma=2.0)
    assert p_miss < p_match
    assert p_miss > 0.0


def test_naive_equal_bounds_without_half_unit_is_zero():
    """Document why resolution_bin expands points: raw Φ(h)-Φ(l) with l==h is 0."""
    t = 80.0
    continuous_point = wb.norm_cdf((t - 80.0) / 2.0) - wb.norm_cdf((t - 80.0) / 2.0)
    assert continuous_point == 0.0
    assert wb.bucket_prob(80, 80, 80, sigma=2.0) > 0.19


# ---------------------------------------------------------------------------
# Edge buckets — CDF via resolution_bin
# ---------------------------------------------------------------------------


def test_or_below_edge_uses_cdf():
    # support (-inf, t_high+0.5); p = Φ((t_high+0.5 - forecast) / s)
    forecast, t_high, s = 48.0, 50.0, 2.0
    expected = wb.norm_cdf((t_high + 0.5 - forecast) / s)
    assert abs(wb.bucket_prob(forecast, -999, t_high, sigma=s) - expected) < 1e-12


def test_or_higher_edge_uses_cdf():
    # support [t_low-0.5, +inf); p = 1 - Φ((t_low-0.5 - forecast) / s)
    forecast, t_low, s = 92.0, 90.0, 2.0
    expected = 1.0 - wb.norm_cdf((t_low - 0.5 - forecast) / s)
    assert abs(wb.bucket_prob(forecast, t_low, 999, sigma=s) - expected) < 1e-12


def test_edge_default_sigma_is_sigma_f_when_none():
    """Omitted σ → SIGMA_F only; °C must pass get_sigma explicitly."""
    forecast, t_high = 50.0, 50.0
    with_default = wb.bucket_prob(forecast, -999, t_high, sigma=None)
    with_f = wb.bucket_prob(forecast, -999, t_high, sigma=wb.SIGMA_F)
    assert with_default == with_f
    assert wb.SIGMA_F == 2.0


def test_edge_probabilities_in_unit_interval():
    p_lo = wb.bucket_prob(40, -999, 50, sigma=2.0)
    p_hi = wb.bucket_prob(100, 90, 999, sigma=2.0)
    assert 0.0 <= p_lo <= 1.0
    assert 0.0 <= p_hi <= 1.0


def test_or_below_far_below_cap_is_high():
    p = wb.bucket_prob(30, -999, 50, sigma=2.0)
    assert p > 0.99


def test_or_higher_far_above_floor_is_high():
    p = wb.bucket_prob(100, 90, 999, sigma=2.0)
    assert p > 0.99


# ---------------------------------------------------------------------------
# Bias shifts μ
# ---------------------------------------------------------------------------


def test_positive_bias_shifts_mass_cooler():
    # Warm forecasts (bias > 0) → debiased μ lower → more mass on cooler bin
    p_cool_no = wb.bucket_prob(80, 78, 79, sigma=2.0, bias=0.0)
    p_cool_bias = wb.bucket_prob(80, 78, 79, sigma=2.0, bias=2.0)
    assert p_cool_bias > p_cool_no


# ---------------------------------------------------------------------------
# Full event partition
# ---------------------------------------------------------------------------


def test_event_bucket_probs_sum_to_one():
    ranges = [(-999, 89), (90, 91), (92, 93), (94, 95), (96, 999)]
    probs = wb.event_bucket_probs(92.0, ranges, sigma=2.0, bias=0.0)
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(0.0 <= p <= 1.0 for p in probs)
    # Mode near 92-93
    assert probs[2] == max(probs)


def test_reference_one_degree_mass_under_sigma_two():
    """~19.7% peak mass in 1° window at σ=2 — why uncalibrated modes refuse 35¢ books."""
    mass = wb.bucket_prob(80, 80, 80, sigma=2.0)
    assert 0.19 < mass < 0.20
