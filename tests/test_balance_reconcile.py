"""
Balance reconstruction vs state.json (issue #1 style inflation).

Ground truth: cash = starting - Σ cost + Σ (cost + pnl) for closed positions.
"""


def _pos(cost, status, pnl=None):
    return {
        "status": status,
        "cost": cost,
        "pnl": pnl,
        "shares": 10.0,
        "entry_price": 0.3,
    }


def test_balance_from_markets_open_and_closed(wb):
    markets = [
        {"position": _pos(20.0, "open")},
        {"position": _pos(15.0, "closed", pnl=-3.0)},
        {"position": None},
        {},
    ]
    # start 1000 - 20 - 15 + (15 - 3) = 977
    out = wb.balance_from_markets(markets, 1000.0)
    assert out["balance"] == 977.0
    assert out["n_open"] == 1
    assert out["n_closed"] == 1


def test_balance_from_markets_empty(wb):
    assert wb.balance_from_markets([], 1000.0)["balance"] == 1000.0


def test_reconcile_detects_inflation(wb):
    m = wb.new_market("nyc", "2026-07-10", {"endDate": ""}, hours=5)
    m["position"] = _pos(20.0, "closed", pnl=-5.0)
    wb.save_market(m)

    st = wb.load_state()
    st["starting_balance"] = 1000.0
    # True: 1000 - 20 + (20 - 5) = 995; store inflated figure like issue #1
    st["balance"] = 1505.82
    st["peak_balance"] = 1505.82
    wb.save_state(st)

    report = wb.reconcile_balance(apply=False)
    assert report["ok"] is False
    assert report["true_balance"] == 995.0
    assert report["delta"] == round(1505.82 - 995.0, 2)
    assert report["applied"] is False
    # Disk unchanged without --fix
    assert wb.load_state()["balance"] == 1505.82


def test_reconcile_fix_writes_true_balance(wb):
    m = wb.new_market("chicago", "2026-07-11", {"endDate": ""}, hours=5)
    m["position"] = _pos(20.0, "closed", pnl=2.5)
    wb.save_market(m)
    m2 = wb.new_market("miami", "2026-07-12", {"endDate": ""}, hours=5)
    m2["position"] = _pos(10.0, "open")
    wb.save_market(m2)

    st = wb.load_state()
    st["starting_balance"] = 1000.0
    # True: 1000 - 20 - 10 + (20 + 2.5) = 992.5
    st["balance"] = 1400.0
    st["peak_balance"] = 1400.0
    wb.save_state(st)

    report = wb.reconcile_balance(apply=True)
    assert report["applied"] is True
    assert report["true_balance"] == 992.5
    st2 = wb.load_state()
    assert st2["balance"] == 992.5
    assert st2["peak_balance"] == 1000.0  # conservative floor after inflation


def test_reconcile_ok_when_matched(wb):
    m = wb.new_market("dallas", "2026-07-13", {"endDate": ""}, hours=5)
    m["position"] = _pos(20.0, "closed", pnl=1.0)
    wb.save_market(m)
    st = wb.load_state()
    st["starting_balance"] = 1000.0
    st["balance"] = 1001.0  # 1000 - 20 + 21
    st["peak_balance"] = 1001.0
    wb.save_state(st)

    report = wb.reconcile_balance(apply=True)
    assert report["ok"] is True
    assert report["applied"] is False
    assert wb.load_state()["balance"] == 1001.0
