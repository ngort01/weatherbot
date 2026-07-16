"""Characterization: market + state JSON storage helpers."""

import json

import weatherbet as wb


def test_market_path(wb):
    p = wb.market_path("nyc", "2026-07-16")
    assert p == wb.MARKETS_DIR / "nyc_2026-07-16.json"


def test_new_market_shape(wb):
    event = {"endDate": "2026-07-17T00:00:00Z"}
    m = wb.new_market("nyc", "2026-07-16", event, hours=24.0)
    assert m["city"] == "nyc"
    assert m["city_name"] == "New York City"
    assert m["station"] == "KLGA"
    assert m["unit"] == "F"
    assert m["status"] == "open"
    assert m["position"] is None
    assert m["actual_temp"] is None
    assert m["forecast_snapshots"] == []
    assert m["event_end_date"] == "2026-07-17T00:00:00Z"
    assert m["hours_at_discovery"] == 24.0


def test_save_load_market_roundtrip(wb):
    event = {"endDate": "2026-07-17T00:00:00Z"}
    m = wb.new_market("chicago", "2026-07-16", event, hours=12.5)
    m["position"] = {"status": "open", "cost": 20.0, "p": 1.0}
    wb.save_market(m)
    loaded = wb.load_market("chicago", "2026-07-16")
    assert loaded["city"] == "chicago"
    assert loaded["position"]["cost"] == 20.0
    assert loaded["hours_at_discovery"] == 12.5


def test_load_market_missing(wb):
    assert wb.load_market("nyc", "1999-01-01") is None


def test_load_all_markets(wb):
    for city, date in [("nyc", "2026-07-16"), ("miami", "2026-07-17")]:
        m = wb.new_market(city, date, {"endDate": ""}, hours=5)
        wb.save_market(m)
    # corrupt file should be skipped
    (wb.MARKETS_DIR / "bad.json").write_text("{not-json", encoding="utf-8")
    all_m = wb.load_all_markets()
    cities = {m["city"] for m in all_m}
    assert cities == {"nyc", "miami"}


def test_state_default_and_roundtrip(wb):
    st = wb.load_state()
    assert st["balance"] == wb.BALANCE
    assert st["total_trades"] == 0
    st["balance"] = 9999.0
    st["wins"] = 3
    wb.save_state(st)
    st2 = wb.load_state()
    assert st2["balance"] == 9999.0
    assert st2["wins"] == 3
