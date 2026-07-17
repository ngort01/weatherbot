"""Portfolio stats derived from market files into state.json."""


def _closed_pos(cost=20.0, pnl=-5.0, reason="stop_loss"):
    return {
        "status": "closed",
        "cost": cost,
        "pnl": pnl,
        "shares": 10.0,
        "entry_price": 0.3,
        "close_reason": reason,
    }


def _open_pos(cost=20.0):
    return {
        "status": "open",
        "cost": cost,
        "pnl": None,
        "shares": 10.0,
        "entry_price": 0.3,
    }


def test_compute_portfolio_stats_basic(wb):
    markets = [
        {
            "position": _closed_pos(pnl=-5.0, reason="stop_loss"),
            "resolved_outcome": "loss",
            "hold_to_resolution_pnl": -20.0,
            "held_to_resolution": False,
            "actual_temp": 80.0,
        },
        {
            "position": _closed_pos(pnl=10.0, reason="forecast_changed"),
            "resolved_outcome": "win",
            "hold_to_resolution_pnl": 40.0,
            "held_to_resolution": False,
        },
        {
            "position": _closed_pos(pnl=15.0, reason="resolved"),
            "resolved_outcome": "win",
            "held_to_resolution": True,
            "hold_to_resolution_pnl": 15.0,
        },
        {"position": _open_pos(cost=20.0)},
        {"position": None},
    ]
    # cash: start 1000, closed return pnl sum = -5+10+15=20, open locks 20
    # true cash = 1000 - 80 + (20-5)+(20+10)+(20+15) = 1000 - 80 + 80 = 1000? 
    # costs 20*4=80, returns for 3 closed: 15+30+35=80, cash=1000-80+80=1000
    # equity = 1000+20=1020
    stats = wb.compute_portfolio_stats(
        markets, starting_balance=1000.0, balance=1000.0, peak_balance=1000.0)

    assert stats["total_trades"] == 4
    assert stats["closed_count"] == 3
    assert stats["open_count"] == 1
    assert stats["open_capital"] == 20.0
    assert stats["realized_pnl"] == 20.0
    assert stats["equity"] == 1020.0
    assert stats["return_pct"] == 2.0
    assert stats["wins"] == 1   # held only
    assert stats["losses"] == 0
    assert stats["bucket_outcomes"] == {"win": 2, "loss": 1, "pending": 1}
    assert stats["exits"]["stop_loss"]["n"] == 1
    assert stats["exits"]["forecast_changed"]["pnl"] == 10.0
    assert stats["exits"]["resolved"]["n"] == 1
    # early exits only in hold_vs_exit (not resolved)
    assert stats["hold_vs_exit"]["annotated"] == 2
    assert stats["hold_vs_exit"]["exit_pnl_sum"] == 5.0   # -5 + 10
    assert stats["hold_vs_exit"]["hold_pnl_sum"] == 20.0  # -20 + 40
    assert stats["hold_vs_exit"]["hold_minus_exit"] == 15.0
    assert stats["actuals_count"] == 1
    assert stats["updated_at"]


def test_refresh_state_stats_writes(wb):
    m = wb.new_market("nyc", "2026-07-16", {"endDate": ""}, hours=5)
    m["position"] = _closed_pos(pnl=-4.0, reason="stop_loss")
    m["resolved_outcome"] = "loss"
    m["hold_to_resolution_pnl"] = -20.0
    wb.save_market(m)

    st = wb.load_state()
    st["starting_balance"] = 1000.0
    st["balance"] = 996.0  # 1000 - 20 + 16
    st["peak_balance"] = 1000.0
    st["total_trades"] = 999  # stale — refresh should fix
    wb.save_state(st)

    out = wb.refresh_state_stats(write=True)
    assert out["total_trades"] == 1
    assert out["closed_count"] == 1
    assert out["realized_pnl"] == -4.0
    assert out["balance"] == 996.0  # cash unchanged
    assert out["equity"] == 996.0
    assert out["bucket_outcomes"]["loss"] == 1

    disk = wb.load_state()
    assert disk["total_trades"] == 1
    assert disk["realized_pnl"] == -4.0


def test_load_state_backfills_missing_keys(wb):
    # Old minimal state.json
    wb.STATE_FILE.write_text(
        '{"balance": 500.0, "starting_balance": 1000.0, '
        '"total_trades": 1, "wins": 0, "losses": 0, "peak_balance": 1000.0}',
        encoding="utf-8",
    )
    st = wb.load_state()
    assert st["balance"] == 500.0
    assert "equity" in st
    assert "exits" in st
    assert "hold_vs_exit" in st
    assert st["bucket_outcomes"]["pending"] == 0
