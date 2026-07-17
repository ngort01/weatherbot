"""
consider_entry — shared entry evaluation (live open path + dry-run scan).
Uses fetch_live_book=False to avoid network.

Under partition p, mode mass at default σ=2 is ~0.38 for a 2° bucket;
EV vs 32¢ mid can clear min_ev=0.05. Tight σ / high price cases use patches.
"""


def _outcome(t_low, t_high, yes=0.32, no=0.68, volume=5000, mid="m1"):
    """yes/no = Gamma outcomePrices (not CLOB bid/ask)."""
    return {
        "question": f"between {t_low}-{t_high}°F",
        "market_id": mid,
        "range": (float(t_low), float(t_high)),
        "yes_price": yes,
        "no_price": no,
        "bid": yes,   # legacy alias
        "ask": no,    # legacy alias — NOT a buy price
        "price": yes,
        "spread": round(abs(no - yes), 4),
        "volume": float(volume),
    }


def _empty_book():
    return {"total": 0, "by_city": {}, "by_date": {}, "capital": 0.0}


def test_consider_entry_would_buy_matched_bucket(wb, patch_config):
    # Tight σ so mode mass high enough that EV clears min_ev at 32¢
    from weatherbet import calibration
    calibration._cal["chicago_hrrr"] = {"sigma": 1.0, "bias": 0.0, "n": 40}
    wb._cal["chicago_hrrr"] = calibration._cal["chicago_hrrr"]

    outcomes = [
        _outcome(70, 71, yes=0.12),
        _outcome(72, 73, yes=0.32, no=0.68, volume=12000),
        _outcome(74, 75, yes=0.18),
    ]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,  # unit test: use yes mid, no network
    )
    assert reason is None, reason
    assert signal is not None
    assert signal["bucket_low"] == 72
    assert signal["bucket_high"] == 73
    assert signal["entry_price"] == 0.32
    assert signal["book_source"] == "yes_mid"
    # Partition p: 2° bin centered near 72 with σ=1 → mass high but < 1
    assert 0.5 < signal["p"] < 1.0
    assert signal["ev"] > 0
    assert signal["bias"] == 0.0
    assert signal["sigma"] == 1.0
    assert signal["cost"] > 0
    assert signal["cost"] <= wb.MAX_BET


def test_consider_entry_no_matching_bucket(wb):
    outcomes = [_outcome(70, 71), _outcome(74, 75)]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    assert signal is None
    assert reason == "no matching bucket"


def test_consider_entry_low_volume(wb):
    outcomes = [_outcome(72, 73, volume=10)]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    assert signal is None
    assert "volume" in reason


def test_consider_entry_max_price(wb, patch_config):
    from weatherbet import calibration
    calibration._cal["chicago_hrrr"] = {"sigma": 1.0, "bias": 0.0, "n": 40}
    wb._cal["chicago_hrrr"] = calibration._cal["chicago_hrrr"]

    outcomes = [_outcome(72, 73, yes=0.50, no=0.50)]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    assert signal is None
    assert "max_price" in reason


def test_consider_entry_skips_negative_ev_at_wide_sigma(wb, patch_config):
    """Uncalibrated σ=2 mode mass on 2° bin is ~0.68; at 40¢ EV may fail min_ev."""
    patch_config("MIN_EV", 0.05)
    # Empty cal → default SIGMA_F=2
    outcomes = [_outcome(72, 73, yes=0.40, no=0.60)]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72.5,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    # p ≈ Φ(1)-Φ(-1) ≈ 0.6827 at 40¢ → EV ≈ 0.6827/0.4 - 1 ≈ +0.707 — actually positive
    # Use a higher price still under max_price to force EV skip
    outcomes = [_outcome(72, 73, yes=0.44, no=0.56)]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72.5,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    # p≈0.68, price=0.44 → EV = 0.68/0.44 - 1 ≈ 0.55 still positive
    # Need p < price for negative-ish EV: use 1° exact-style via range width 1
    outcomes = [{
        "question": "be 80°F",
        "market_id": "m1",
        "range": (80.0, 80.0),
        "yes_price": 0.35,
        "no_price": 0.65,
        "bid": 0.35,
        "ask": 0.65,
        "price": 0.35,
        "spread": 0.3,
        "volume": 5000.0,
    }]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=80.0,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    # p≈0.197 at 35¢ → EV deeply negative
    assert signal is None
    assert reason is not None and ("EV" in reason or "size" in reason)


def test_consider_entry_risk_cap(wb, patch_config):
    from weatherbet import calibration
    calibration._cal["chicago_hrrr"] = {"sigma": 1.0, "bias": 0.0, "n": 40}
    wb._cal["chicago_hrrr"] = calibration._cal["chicago_hrrr"]

    patch_config("MAX_OPEN_POSITIONS", 0)
    outcomes = [_outcome(72, 73)]
    signal, reason = wb.consider_entry(
        "chicago",
        "2026-07-17",
        outcomes,
        forecast_temp=72,
        best_source="hrrr",
        hours=36.0,
        balance=10_000.0,
        book=_empty_book(),
        fetch_live_book=False,
    )
    assert signal is None
    assert reason is not None and reason.startswith("risk:")


def test_parse_event_outcomes_sorts_and_parses(wb):
    event = {
        "markets": [
            {
                "id": "2",
                "question": "Will the highest temperature in Chicago be between 74-75°F on July 17?",
                "volume": 100,
                "outcomePrices": "[0.2, 0.25]",
            },
            {
                "id": "1",
                "question": "Will the highest temperature in Chicago be between 72-73°F on July 17?",
                "volume": 200,
                "outcomePrices": "[0.3, 0.32]",
            },
            {
                "id": "x",
                "question": "not a temp market",
                "volume": 1,
                "outcomePrices": "[0.5, 0.5]",
            },
        ]
    }
    outs = wb.parse_event_outcomes(event)
    assert len(outs) == 2
    assert outs[0]["range"][0] == 72
    assert outs[0]["yes_price"] == 0.3
    assert outs[0]["no_price"] == 0.32  # not a CLOB ask
    assert outs[1]["range"][0] == 74
