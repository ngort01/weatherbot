"""
Characterization: calc_ev, calc_kelly, bet_size under current config defaults.

config.json: kelly_fraction=0.25, max_bet=20.0
"""

import weatherbet as wb


def test_config_pins_expected_by_characterization_suite():
    assert wb.KELLY_FRACTION == 0.25
    assert wb.MAX_BET == 20.0


def test_calc_ev_p_one_at_thirty_five_cents():
    # p/price - 1 when p=1 → why matched trades look fantastic
    ev = wb.calc_ev(1.0, 0.35)
    expected = round(1.0 / 0.35 - 1.0, 4)
    assert ev == expected
    assert ev > 1.0


def test_calc_ev_formula():
    p, price = 0.6, 0.4
    expected = round(p * (1.0 / price - 1.0) - (1.0 - p), 4)
    assert wb.calc_ev(p, price) == expected


def test_calc_ev_bad_prices():
    assert wb.calc_ev(0.5, 0.0) == 0.0
    assert wb.calc_ev(0.5, 1.0) == 0.0
    assert wb.calc_ev(0.5, -0.1) == 0.0


def test_partition_one_degree_mode_negative_ev_at_market_favorite():
    """σ=2 exact-bin mass ~19.7% at 35¢ is deep negative EV (live partition p)."""
    p = wb.bucket_prob(80, 80, 80, sigma=2.0)
    assert 0.19 < p < 0.20
    ev = wb.calc_ev(p, 0.35)
    assert ev < -0.4


def test_calc_kelly_partial_p_below_max_fraction():
    # p=0.4, price=0.3 → full kelly = (0.4*b - 0.6)/b with b=1/0.3-1
    k = wb.calc_kelly(0.4, 0.3)
    b = 1.0 / 0.3 - 1.0
    full = (0.4 * b - 0.6) / b
    expected = round(min(max(0.0, full) * wb.KELLY_FRACTION, 1.0), 4)
    assert k == expected
    assert 0.0 < k < wb.KELLY_FRACTION


def test_calc_kelly_p_one():
    # f = (p*b - (1-p)) / b = 1 when p=1; then * kelly_fraction, cap 1
    k = wb.calc_kelly(1.0, 0.35)
    assert k == 0.25  # full kelly * 0.25


def test_calc_kelly_no_edge():
    # fair price when p=0.5 is 0.5 → kelly 0
    assert wb.calc_kelly(0.5, 0.5) == 0.0


def test_calc_kelly_bad_prices():
    assert wb.calc_kelly(0.9, 0.0) == 0.0
    assert wb.calc_kelly(0.9, 1.0) == 0.0


def test_calc_kelly_clamped_non_negative():
    # bad price relative to p → negative raw kelly → 0
    assert wb.calc_kelly(0.1, 0.5) == 0.0


def test_bet_size_hits_max_bet_on_large_bankroll():
    # kelly 0.25 * 10000 = 2500 → capped at MAX_BET 20
    assert wb.bet_size(0.25, 10000.0) == 20.0


def test_bet_size_scales_when_small():
    # 0.01 * 100 = 1.0
    assert wb.bet_size(0.01, 100.0) == 1.0


def test_bet_size_rounds_to_cents():
    assert wb.bet_size(0.3333, 10.0) == round(0.3333 * 10.0, 2)
