"""Offline unit tests for dashboard aggregation helpers."""
import sys
from pathlib import Path

import pytest

DASH = Path(__file__).resolve().parents[1] / "dashboard"
sys.path.insert(0, str(DASH))

from aggregations import (  # noqa: E402
    balance_from_markets,
    build_dashboard,
    city_stats,
    cumulative_pnl_series,
    exit_breakdown,
    flatten_trades,
    source_accuracy,
    source_trade_pnl,
)


def _market(city, date, *, pos=None, actual=None, snaps=None, unit="F", **extra):
    m = {
        "city": city,
        "city_name": city.title(),
        "date": date,
        "unit": unit,
        "station": "XXXX",
        "status": "open",
        "position": pos,
        "actual_temp": actual,
        "forecast_snapshots": snaps or [],
        "market_snapshots": [],
        "all_outcomes": [],
    }
    m.update(extra)
    return m


def _closed_pos(pnl, src="ecmwf", reason="stop_loss", **kw):
    p = {
        "status": "closed",
        "pnl": pnl,
        "cost": 20.0,
        "forecast_src": src,
        "close_reason": reason,
        "opened_at": "2026-07-15T12:00:00+00:00",
        "closed_at": "2026-07-15T14:00:00+00:00",
        "entry_price": 0.4,
        "bucket_low": 80,
        "bucket_high": 81,
    }
    p.update(kw)
    return p


def test_balance_from_markets_open_and_closed():
    markets = [
        _market("nyc", "2026-07-16", pos={
            "status": "open", "cost": 20.0, "pnl": None,
        }),
        _market("chi", "2026-07-16", pos=_closed_pos(-5.0)),
    ]
    bal = balance_from_markets(markets, 10000.0)
    # open locks 20; closed returned 20-5=15 → cash = 10000 - 20 - 20 + 15 = 9975
    assert bal["balance"] == 9975.0
    assert bal["n_open"] == 1
    assert bal["n_closed"] == 1


def test_flatten_and_exit_breakdown():
    markets = [
        _market("a", "2026-07-16", pos=_closed_pos(-10, reason="stop_loss")),
        _market("b", "2026-07-16", pos=_closed_pos(5, reason="forecast_changed")),
        _market("c", "2026-07-16", pos={"status": "open", "cost": 20, "forecast_src": "hrrr"}),
    ]
    trades = flatten_trades(markets)
    assert len(trades) == 3
    exits = exit_breakdown(trades)
    assert exits["stop_loss"]["n"] == 1
    assert exits["stop_loss"]["pnl"] == -10
    assert exits["forecast_changed"]["pnl"] == 5


def test_cumulative_pnl_series_sorted():
    trades = [
        {"position_status": "closed", "closed_at": "2026-07-16T10:00:00+00:00",
         "pnl": 10, "id": "a", "city": "a", "close_reason": "x"},
        {"position_status": "closed", "closed_at": "2026-07-15T10:00:00+00:00",
         "pnl": -4, "id": "b", "city": "b", "close_reason": "y"},
    ]
    series = cumulative_pnl_series(trades)
    assert [s["cum_pnl"] for s in series] == [-4, 6]


def test_city_stats_and_source_pnl():
    markets = [
        _market("seattle", "2026-07-16", unit="F", actual=80,
                pos=_closed_pos(-8, src="hrrr"),
                snaps=[{"ts": "t", "hrrr": 87, "ecmwf": 79, "best": 87, "best_source": "hrrr"}]),
        _market("seattle", "2026-07-17", unit="F",
                pos=_closed_pos(3, src="ecmwf", reason="resolved")),
        _market("london", "2026-07-16", unit="C", actual=22,
                snaps=[{"ts": "t", "ecmwf": 21, "best": 21, "best_source": "ecmwf"}]),
    ]
    cities = city_stats(markets)
    sea = next(c for c in cities if c["city"] == "seattle")
    assert sea["closed"] == 2
    assert sea["realized_pnl"] == pytest.approx(-5.0)
    assert sea["best_n"] == 1

    trades = flatten_trades(markets)
    by_src = {r["source"]: r for r in source_trade_pnl(trades)}
    assert by_src["hrrr"]["n"] == 1
    assert by_src["hrrr"]["pnl"] == -8

    acc = source_accuracy(markets)
    assert acc["last_snap"]["F"]["hrrr"]["n"] == 1
    assert acc["last_snap"]["F"]["hrrr"]["mae"] == pytest.approx(7.0)
    assert acc["hrrr_ecmwf_spread"]["n"] == 1
    assert acc["hrrr_ecmwf_spread"]["mean"] == pytest.approx(8.0)


def test_build_dashboard_empty_dir(tmp_path):
    payload = build_dashboard(tmp_path)
    assert payload["summary"]["total_trades"] == 0
    assert payload["trades"] == []
    assert payload["cities"] == []
