"""model_vs_market reporting — pure, offline, no trading side effects."""


def _mkt(
    city="chicago",
    date="2026-07-17",
    forecast=72.5,
    source="hrrr",
    outcomes=None,
    position=None,
    unit="F",
):
    if outcomes is None:
        outcomes = [
            {
                "market_id": "a",
                "range": (70.0, 71.0),
                "yes_price": 0.15,
                "price": 0.15,
            },
            {
                "market_id": "b",
                "range": (72.0, 73.0),
                "yes_price": 0.35,
                "price": 0.35,
            },
            {
                "market_id": "c",
                "range": (74.0, 75.0),
                "yes_price": 0.20,
                "price": 0.20,
            },
        ]
    return {
        "city": city,
        "city_name": "Chicago",
        "date": date,
        "unit": unit,
        "status": "open",
        "position": position,
        "forecast_snapshots": [
            {"best": forecast, "best_source": source, "hrrr": forecast},
        ],
        "all_outcomes": outcomes,
    }


def test_model_vs_market_rows_basic(wb):
    rows = wb.model_vs_market_rows([_mkt()])
    assert len(rows) == 1
    r = rows[0]
    assert r["bucket_low"] == 72.0
    assert r["bucket_high"] == 73.0
    assert r["matched_price"] == 0.35
    assert r["matched_is_favorite"] is True
    assert 0.0 < r["model_p"] < 1.0
    # default σ=2, 2° bin mid → mass ~0.38
    assert 0.3 < r["model_p"] < 0.5
    # EV computed on full p before model_p is rounded for display
    assert abs(r["ev"] - wb.calc_ev(r["model_p"], 0.35)) < 0.01


def test_model_vs_market_skips_no_match(wb):
    rows = wb.model_vs_market_rows([
        _mkt(forecast=90.0),  # outside 70-75 outcomes
    ])
    assert rows == []


def test_summarize_counts_ev_gates(wb, patch_config):
    # Tight σ so EV may pass
    from weatherbet import calibration
    calibration._cal["chicago_hrrr"] = {"sigma": 0.8, "bias": 0.0, "n": 40}
    wb._cal["chicago_hrrr"] = calibration._cal["chicago_hrrr"]

    rows = wb.model_vs_market_rows([
        _mkt(forecast=72.5),
        _mkt(
            date="2026-07-18",
            forecast=72.5,
            outcomes=[{
                "market_id": "x",
                "range": (72.0, 73.0),
                "yes_price": 0.80,
                "price": 0.80,
            }],
        ),
    ])
    summary = wb.summarize_model_vs_market(rows, min_ev=0.05)
    assert summary["n"] == 2
    assert summary["ev_pass"] + summary["ev_neg"] >= 1
    assert "mean_model_p" in summary


def test_print_status_includes_section(wb, capsys, monkeypatch):
    """Smoke: status prints model vs market without crashing."""
    # Redirect markets via wb fixture paths — empty dir is fine
    wb.print_status()
    out = capsys.readouterr().out
    assert "Model vs market" in out
    assert "Calibration" in out
