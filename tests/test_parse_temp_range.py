"""Characterization: parse_temp_range — Polymarket question shapes."""

import weatherbet as wb


def test_or_below_f():
    q = "Will the highest temperature in Chicago be 50°F or below on July 16?"
    assert wb.parse_temp_range(q) == (-999.0, 50.0)


def test_or_higher_f():
    q = "Will the highest temperature in NYC be 90°F or higher on July 16?"
    assert wb.parse_temp_range(q) == (90.0, 999.0)


def test_between_range_f():
    q = "Will the highest temperature in Chicago be between 46-47°F on March 7?"
    assert wb.parse_temp_range(q) == (46.0, 47.0)


def test_exact_temp_f_zero_width():
    # Zero-width bucket: t_low == t_high
    q = "Will the highest temperature in Dallas be 80°F on July 16?"
    assert wb.parse_temp_range(q) == (80.0, 80.0)


def test_exact_temp_c_zero_width():
    q = "Will the highest temperature in London be 26°C on July 16?"
    assert wb.parse_temp_range(q) == (26.0, 26.0)


def test_between_celsius():
    q = "Will the highest temperature in Paris be between 22-23°C on July 16?"
    assert wb.parse_temp_range(q) == (22.0, 23.0)


def test_empty_and_garbage():
    assert wb.parse_temp_range("") is None
    assert wb.parse_temp_range(None) is None
    assert wb.parse_temp_range("Will it rain tomorrow?") is None


def test_or_below_without_degree_symbol():
    q = "Will the highest temperature in Miami be 85F or below on July 16?"
    assert wb.parse_temp_range(q) == (-999.0, 85.0)
