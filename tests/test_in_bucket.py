"""Characterization: in_bucket membership rules."""

import weatherbet as wb


def test_zero_width_exact_match():
    assert wb.in_bucket(80, 80, 80) is True


def test_zero_width_rounds_forecast():
    # round(80.4) == 80
    assert wb.in_bucket(80.4, 80, 80) is True
    # round(80.5) is banker's rounding in Python 3: to even → 80
    assert wb.in_bucket(80.5, 80, 80) is True
    # round(80.6) == 81
    assert wb.in_bucket(80.6, 80, 80) is False


def test_zero_width_miss():
    assert wb.in_bucket(81, 80, 80) is False
    assert wb.in_bucket(79, 80, 80) is False


def test_range_inclusive():
    assert wb.in_bucket(46.0, 46, 47) is True
    assert wb.in_bucket(47.0, 46, 47) is True
    assert wb.in_bucket(46.5, 46, 47) is True


def test_range_outside():
    assert wb.in_bucket(45.9, 46, 47) is False
    assert wb.in_bucket(47.1, 46, 47) is False
