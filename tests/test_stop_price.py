"""compute_stop_price — absolute width floor vs percent-only."""


def test_stop_uses_pct_when_wider_than_floor(wb):
    # 0.32 × 0.20 = 0.064 > 0.05 → stop 0.256
    assert wb.compute_stop_price(0.32) == 0.256


def test_stop_uses_min_width_on_cheap_mids(wb):
    # 0.10 × 0.20 = 0.02 < 0.05 → stop 0.05
    assert wb.compute_stop_price(0.10) == 0.05


def test_stop_rejects_subcent_room_at_penny_prices(wb):
    # Old behavior: 0.023 * 0.80 = 0.0184 (0.5¢ room). New: 5¢ floor → 0.
    assert wb.compute_stop_price(0.023) == 0.0
    # At min_price 0.08: 0.08 - 0.05 = 0.03 (≥ 3¢ room)
    assert wb.compute_stop_price(0.08) == 0.03


def test_stop_custom_params(wb):
    assert wb.compute_stop_price(0.40, stop_pct=0.10, min_width=0.02) == 0.36
    assert wb.compute_stop_price(0.40, stop_pct=0.10, min_width=0.10) == 0.30


def test_stop_invalid_entry(wb):
    assert wb.compute_stop_price(None) is None
    assert wb.compute_stop_price(0) == 0.0
    assert wb.compute_stop_price(-1) == 0.0
