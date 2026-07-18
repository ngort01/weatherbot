"""
should_exit_on_forecast / residual_edge — forecast exit residual-edge gate.

Only dump on forecast drift when model p no longer exceeds salvage bid.
Characterization of IMPROVEMENTS §12 (Paris-17 hold, edge-gone sell).
"""
import pytest


def test_residual_edge_basic(wb):
    assert wb.residual_edge(0.087, 0.006) == pytest.approx(0.081)
    assert wb.residual_edge(0.04, 0.075) == pytest.approx(-0.035)
    assert wb.residual_edge(None, 0.1) is None
    assert wb.residual_edge(0.2, None) is None


def test_should_exit_missing_bid_holds(wb):
    assert wb.should_exit_on_forecast(0.5, None) is False
    assert wb.should_exit_on_forecast(None, 0.1) is False


def test_paris17_style_hold_when_p_exceeds_dust_bid(wb):
    """
    Paris Jul 17 class: mode left 26°C (fc~28), but p≈0.087 ≫ bid 0.006.
    Old rule sold for −$19; residual-edge holds.
    """
    p = wb.bucket_prob(28.0, 26.0, 26.0, sigma=1.2)
    assert p > 0.05
    bid = 0.006
    assert wb.residual_edge(p, bid) > 0
    assert wb.should_exit_on_forecast(p, bid) is False


def test_edge_gone_exits(wb):
    """Model mass at or below salvage bid → forecast exit fires."""
    assert wb.should_exit_on_forecast(0.04, 0.075) is True
    assert wb.should_exit_on_forecast(0.20, 0.20) is True  # edge == 0
    assert wb.should_exit_on_forecast(0.10, 0.22) is True


def test_toronto_style_exit_when_market_rich(wb):
    """fc away from bucket and market bid still above model p → exit."""
    p = wb.bucket_prob(29.3, 28.0, 28.0, sigma=1.2)
    bid = 0.235
    assert p < bid
    assert wb.should_exit_on_forecast(p, bid) is True


def test_min_edge_cushion(wb, patch_config):
    """Positive min_edge requires stricter residual before holding."""
    patch_config("FORECAST_EXIT_MIN_EDGE", 0.05)
    # edge = 0.03 → exit under 0.05 floor
    assert wb.should_exit_on_forecast(0.10, 0.07) is True
    # edge = 0.08 → hold
    assert wb.should_exit_on_forecast(0.15, 0.07) is False
    # explicit override ignores config
    assert wb.should_exit_on_forecast(0.10, 0.07, min_edge=0.0) is False


def test_default_min_edge_is_zero(wb):
    assert wb.FORECAST_EXIT_MIN_EDGE == 0.0
    assert wb.should_exit_on_forecast(0.081, 0.080) is False
    assert wb.should_exit_on_forecast(0.079, 0.080) is True
