"""Portfolio risk caps (IMPROVEMENTS §3)."""

import weatherbet as wb


def test_portfolio_snapshot_empty(wb):
    snap = wb.portfolio_snapshot([])
    assert snap == {"total": 0, "by_city": {}, "by_date": {}, "capital": 0.0}


def test_portfolio_snapshot_counts(wb):
    markets = [
        {
            "city": "nyc",
            "date": "2026-07-16",
            "position": {"status": "open", "cost": 20.0},
        },
        {
            "city": "nyc",
            "date": "2026-07-17",
            "position": {"status": "open", "cost": 10.0},
        },
        {
            "city": "london",
            "date": "2026-07-16",
            "position": {"status": "closed", "cost": 20.0},
        },
    ]
    snap = wb.portfolio_snapshot(markets)
    assert snap["total"] == 2
    assert snap["by_city"]["nyc"] == 2
    assert snap["by_date"]["2026-07-16"] == 1
    assert snap["capital"] == 30.0


def test_risk_limit_max_open_positions(wb, patch_config):
    patch_config("MAX_OPEN_POSITIONS", 2)
    patch_config("MAX_OPEN_PER_CITY", 99)
    patch_config("MAX_OPEN_PER_DATE", 99)
    patch_config("MAX_CAPITAL_AT_RISK_PCT", 1.0)
    book = {"total": 2, "by_city": {}, "by_date": {}, "capital": 40.0}
    reason = wb.risk_limit_reason("miami", "2026-07-18", 20.0, 9000.0, book)
    assert reason is not None
    assert "max open positions" in reason


def test_risk_limit_max_per_city(wb, patch_config):
    patch_config("MAX_OPEN_POSITIONS", 99)
    patch_config("MAX_OPEN_PER_CITY", 1)
    patch_config("MAX_OPEN_PER_DATE", 99)
    patch_config("MAX_CAPITAL_AT_RISK_PCT", 1.0)
    book = {"total": 1, "by_city": {"nyc": 1}, "by_date": {}, "capital": 20.0}
    assert wb.risk_limit_reason("nyc", "2026-07-18", 20.0, 9000.0, book)
    assert wb.risk_limit_reason("miami", "2026-07-18", 20.0, 9000.0, book) is None


def test_risk_limit_max_per_date(wb, patch_config):
    patch_config("MAX_OPEN_POSITIONS", 99)
    patch_config("MAX_OPEN_PER_CITY", 99)
    patch_config("MAX_OPEN_PER_DATE", 2)
    patch_config("MAX_CAPITAL_AT_RISK_PCT", 1.0)
    book = {
        "total": 2,
        "by_city": {"nyc": 1, "london": 1},
        "by_date": {"2026-07-16": 2},
        "capital": 40.0,
    }
    assert wb.risk_limit_reason("miami", "2026-07-16", 20.0, 9000.0, book)
    assert wb.risk_limit_reason("miami", "2026-07-17", 20.0, 9000.0, book) is None


def test_risk_limit_capital_at_risk(wb, patch_config):
    patch_config("MAX_OPEN_POSITIONS", 99)
    patch_config("MAX_OPEN_PER_CITY", 99)
    patch_config("MAX_OPEN_PER_DATE", 99)
    patch_config("MAX_CAPITAL_AT_RISK_PCT", 0.15)
    # equity = balance + capital = 8500 + 1500 = 10000; 15% = 1500 already at cap
    book = {"total": 5, "by_city": {}, "by_date": {}, "capital": 1500.0}
    assert wb.risk_limit_reason("nyc", "2026-07-16", 20.0, 8500.0, book)
    # under cap
    book2 = {"total": 1, "by_city": {}, "by_date": {}, "capital": 100.0}
    assert wb.risk_limit_reason("nyc", "2026-07-16", 20.0, 9900.0, book2) is None


def test_book_register_open_close(wb):
    book = {"total": 0, "by_city": {}, "by_date": {}, "capital": 0.0}
    wb.book_register_open(book, "nyc", "2026-07-16", 20.0)
    assert book["total"] == 1
    assert book["capital"] == 20.0
    wb.book_register_close(book, "nyc", "2026-07-16", 20.0)
    assert book["total"] == 0
    assert book["capital"] == 0.0
