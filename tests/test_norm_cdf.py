"""Characterization: norm_cdf"""

import math

import weatherbet as wb


def test_norm_cdf_zero_is_half():
    assert abs(wb.norm_cdf(0.0) - 0.5) < 1e-12


def test_norm_cdf_symmetric():
    x = 1.25
    assert abs(wb.norm_cdf(x) + wb.norm_cdf(-x) - 1.0) < 1e-12


def test_norm_cdf_monotone():
    assert wb.norm_cdf(-2.0) < wb.norm_cdf(0.0) < wb.norm_cdf(2.0)


def test_norm_cdf_matches_erf_definition():
    x = 0.5
    expected = 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    assert abs(wb.norm_cdf(x) - expected) < 1e-15
