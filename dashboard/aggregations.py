"""
Pure aggregation helpers for the paper-trading dashboard.

Reads market dicts / state / calibration — no network, no weatherbet imports
(avoids config.json side effects at import).
"""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

# Snapshot meta keys — everything else with a numeric value is a forecast source.
_SNAP_META = frozenset({
    "ts", "horizon", "hours_left", "best", "best_source",
})


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_markets(data_dir: Path) -> list[dict]:
    markets_dir = data_dir / "markets"
    if not markets_dir.is_dir():
        return []
    out = []
    for path in sorted(markets_dir.glob("*.json")):
        try:
            out.append(load_json(path))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_state(data_dir: Path) -> dict:
    path = data_dir / "state.json"
    if not path.is_file():
        return {}
    try:
        return load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def load_calibration(data_dir: Path) -> dict:
    path = data_dir / "calibration.json"
    if not path.is_file():
        return {}
    try:
        data = load_json(path)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _f(val, default=None):
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _source_keys_in_snap(snap: dict) -> list[str]:
    keys = []
    for k, v in snap.items():
        if k in _SNAP_META:
            continue
        if _f(v) is not None:
            keys.append(k)
    return keys


def _parse_iso(ts: str):
    from datetime import datetime
    t = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(t)


def _snap_nearest_ts(snaps: list, target_ts: str | None) -> dict | None:
    if not snaps:
        return None
    if not target_ts:
        return snaps[-1]
    try:
        target = _parse_iso(target_ts)
    except Exception:
        return snaps[-1]
    best = snaps[0]
    best_abs = None
    for s in snaps:
        ts = s.get("ts")
        if not ts:
            continue
        try:
            d = abs((_parse_iso(ts) - target).total_seconds())
        except Exception:
            continue
        if best_abs is None or d < best_abs:
            best_abs = d
            best = s
    return best


def balance_from_markets(markets: list[dict], starting_balance: float) -> dict:
    """Ground-truth paper cash (mirrors weatherbet.state.balance_from_markets)."""
    total_cost = 0.0
    total_returned = 0.0
    n_open = 0
    n_closed = 0
    for m in markets:
        pos = m.get("position")
        if not pos:
            continue
        cost = _f(pos.get("cost"), 0.0) or 0.0
        total_cost += cost
        if pos.get("status") == "closed":
            n_closed += 1
            pnl = _f(pos.get("pnl"), 0.0) or 0.0
            total_returned += cost + pnl
        else:
            n_open += 1
    balance = round(float(starting_balance) - total_cost + total_returned, 2)
    return {
        "balance": balance,
        "starting_balance": float(starting_balance),
        "total_cost": round(total_cost, 2),
        "total_returned": round(total_returned, 2),
        "n_open": n_open,
        "n_closed": n_closed,
    }


def _open_capital(markets: list[dict]) -> float:
    total = 0.0
    for m in markets:
        pos = m.get("position")
        if pos and pos.get("status") == "open":
            total += _f(pos.get("cost"), 0.0) or 0.0
    return round(total, 2)


def flatten_trades(markets: list[dict]) -> list[dict]:
    rows = []
    for m in markets:
        pos = m.get("position")
        if not pos:
            continue
        rows.append({
            "id": f"{m.get('city')}_{m.get('date')}",
            "city": m.get("city"),
            "city_name": m.get("city_name") or m.get("city"),
            "date": m.get("date"),
            "unit": m.get("unit"),
            "station": m.get("station"),
            "market_status": m.get("status"),
            "resolved": bool(m.get("resolved")),
            "resolved_outcome": m.get("resolved_outcome"),
            "actual_temp": _f(m.get("actual_temp")),
            "held_to_resolution": m.get("held_to_resolution"),
            "hold_to_resolution_pnl": _f(m.get("hold_to_resolution_pnl")),
            "market_pnl": _f(m.get("pnl")),
            "position_status": pos.get("status"),
            "question": pos.get("question"),
            "market_id": pos.get("market_id"),
            "bucket_low": _f(pos.get("bucket_low")),
            "bucket_high": _f(pos.get("bucket_high")),
            "entry_price": _f(pos.get("entry_price")),
            "exit_price": _f(pos.get("exit_price")),
            "bid_at_entry": _f(pos.get("bid_at_entry")),
            "spread": _f(pos.get("spread")),
            "shares": _f(pos.get("shares")),
            "cost": _f(pos.get("cost")),
            "p": _f(pos.get("p")),
            "ev": _f(pos.get("ev")),
            "kelly": _f(pos.get("kelly")),
            "forecast_temp": _f(pos.get("forecast_temp")),
            "forecast_src": pos.get("forecast_src"),
            "sigma": _f(pos.get("sigma")),
            "bias": _f(pos.get("bias")),
            "pnl": _f(pos.get("pnl")),
            "close_reason": pos.get("close_reason"),
            "opened_at": pos.get("opened_at"),
            "closed_at": pos.get("closed_at"),
            "stop_price": _f(pos.get("stop_price")),
            "book_source": pos.get("book_source"),
            "trailing_activated": pos.get("trailing_activated"),
            "forecast_panel": pos.get("forecast_panel"),
            "liquidity_usd": _f(pos.get("liquidity_usd")),
        })
    rows.sort(key=lambda r: (r.get("opened_at") or "", r.get("id") or ""), reverse=True)
    return rows


def cumulative_pnl_series(trades: list[dict]) -> list[dict]:
    closed = [
        t for t in trades
        if t.get("position_status") == "closed" and t.get("closed_at")
    ]
    closed.sort(key=lambda t: t["closed_at"])
    cum = 0.0
    series = []
    for t in closed:
        cum = round(cum + (_f(t.get("pnl"), 0.0) or 0.0), 4)
        series.append({
            "ts": t["closed_at"],
            "pnl": _f(t.get("pnl"), 0.0) or 0.0,
            "cum_pnl": cum,
            "id": t["id"],
            "city": t["city"],
            "close_reason": t.get("close_reason"),
        })
    return series


def exit_breakdown(trades: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in trades:
        if t.get("position_status") != "closed":
            continue
        reason = t.get("close_reason") or "unknown"
        bucket = out.setdefault(reason, {"n": 0, "pnl": 0.0})
        bucket["n"] += 1
        bucket["pnl"] = round(bucket["pnl"] + (_f(t.get("pnl"), 0.0) or 0.0), 4)
    return out


def city_stats(markets: list[dict]) -> list[dict]:
    by_city: dict[str, dict] = {}
    for m in markets:
        city = m.get("city") or "?"
        row = by_city.setdefault(city, {
            "city": city,
            "city_name": m.get("city_name") or city,
            "unit": m.get("unit"),
            "station": m.get("station"),
            "markets": 0,
            "with_actual": 0,
            "trades": 0,
            "open": 0,
            "closed": 0,
            "realized_pnl": 0.0,
            "pnls": [],
            "exits": defaultdict(int),
            "bucket_win": 0,
            "bucket_loss": 0,
            "bucket_pending": 0,
            "best_residuals": [],
        })
        row["markets"] += 1
        if m.get("city_name"):
            row["city_name"] = m["city_name"]
        if m.get("unit"):
            row["unit"] = m["unit"]
        if m.get("station"):
            row["station"] = m["station"]

        actual = _f(m.get("actual_temp"))
        if actual is not None:
            row["with_actual"] += 1
            snaps = m.get("forecast_snapshots") or []
            if snaps:
                last = snaps[-1]
                best = _f(last.get("best"))
                if best is not None:
                    row["best_residuals"].append(best - actual)

        pos = m.get("position")
        if pos:
            row["trades"] += 1
            if pos.get("status") == "open":
                row["open"] += 1
            elif pos.get("status") == "closed":
                row["closed"] += 1
                pnl = _f(pos.get("pnl"), 0.0) or 0.0
                row["realized_pnl"] = round(row["realized_pnl"] + pnl, 4)
                row["pnls"].append(pnl)
                reason = pos.get("close_reason") or "unknown"
                row["exits"][reason] += 1

        ro = m.get("resolved_outcome")
        if pos and ro == "win":
            row["bucket_win"] += 1
        elif pos and ro == "loss":
            row["bucket_loss"] += 1
        elif pos:
            row["bucket_pending"] += 1

    result = []
    for city, row in by_city.items():
        pnls = row.pop("pnls")
        residuals = row.pop("best_residuals")
        exits = dict(row.pop("exits"))
        n_closed = row["closed"]
        result.append({
            **row,
            "realized_pnl": round(row["realized_pnl"], 2),
            "avg_pnl": round(statistics.mean(pnls), 4) if pnls else None,
            "median_pnl": round(statistics.median(pnls), 4) if pnls else None,
            "exits": exits,
            "best_mae": round(statistics.mean(abs(r) for r in residuals), 4) if residuals else None,
            "best_bias": round(statistics.mean(residuals), 4) if residuals else None,
            "best_n": len(residuals),
        })
    result.sort(key=lambda r: (r["realized_pnl"], r["city"]))
    return result


def _error_stats(errors: list[float]) -> dict:
    if not errors:
        return {"n": 0, "bias": None, "mae": None, "rmse": None}
    n = len(errors)
    bias = sum(errors) / n
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    return {
        "n": n,
        "bias": round(bias, 4),
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
    }


def source_accuracy(markets: list[dict]) -> dict:
    """
    Residual stats per forecast source, split by unit.

    - last_snap: last snapshot residual vs actual_temp
    - at_entry: snap nearest opened_at (markets with positions only)
    """
    last_by_unit_src: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    entry_by_unit_src: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    hrrr_ecmwf_spreads: list[float] = []

    for m in markets:
        actual = _f(m.get("actual_temp"))
        unit = m.get("unit") or "?"
        snaps = m.get("forecast_snapshots") or []

        if snaps:
            for s in snaps:
                h = _f(s.get("hrrr"))
                e = _f(s.get("ecmwf"))
                if h is not None and e is not None:
                    hrrr_ecmwf_spreads.append(abs(h - e))

        if actual is not None and snaps:
            last = snaps[-1]
            for src in _source_keys_in_snap(last):
                val = _f(last.get(src))
                if val is not None:
                    last_by_unit_src[unit][src].append(val - actual)
            best = _f(last.get("best"))
            if best is not None:
                last_by_unit_src[unit]["best"].append(best - actual)

        pos = m.get("position")
        if pos and actual is not None and snaps:
            snap = _snap_nearest_ts(snaps, pos.get("opened_at"))
            if snap:
                for src in _source_keys_in_snap(snap):
                    val = _f(snap.get(src))
                    if val is not None:
                        entry_by_unit_src[unit][src].append(val - actual)

    def pack(nested):
        out = {}
        for unit, srcs in nested.items():
            out[unit] = {
                src: _error_stats(errs)
                for src, errs in sorted(srcs.items())
            }
        return out

    spread_stats = None
    if hrrr_ecmwf_spreads:
        hrrr_ecmwf_spreads.sort()
        n = len(hrrr_ecmwf_spreads)

        def pct(p):
            i = min(n - 1, max(0, int(round((p / 100) * (n - 1)))))
            return round(hrrr_ecmwf_spreads[i], 4)

        spread_stats = {
            "n": n,
            "mean": round(sum(hrrr_ecmwf_spreads) / n, 4),
            "p50": pct(50),
            "p90": pct(90),
            "p95": pct(95),
            "max": round(hrrr_ecmwf_spreads[-1], 4),
        }

    return {
        "last_snap": pack(last_by_unit_src),
        "at_entry": pack(entry_by_unit_src),
        "hrrr_ecmwf_spread": spread_stats,
    }


def source_trade_pnl(trades: list[dict]) -> list[dict]:
    by_src: dict[str, dict] = {}
    for t in trades:
        if t.get("position_status") != "closed":
            continue
        src = t.get("forecast_src") or "unknown"
        row = by_src.setdefault(src, {
            "source": src,
            "n": 0,
            "pnl": 0.0,
            "pnls": [],
            "exits": defaultdict(int),
        })
        row["n"] += 1
        pnl = _f(t.get("pnl"), 0.0) or 0.0
        row["pnl"] = round(row["pnl"] + pnl, 4)
        row["pnls"].append(pnl)
        reason = t.get("close_reason") or "unknown"
        row["exits"][reason] += 1

    out = []
    for src, row in by_src.items():
        pnls = row.pop("pnls")
        exits = dict(row.pop("exits"))
        out.append({
            "source": src,
            "n": row["n"],
            "pnl": round(row["pnl"], 2),
            "avg_pnl": round(statistics.mean(pnls), 4) if pnls else None,
            "median_pnl": round(statistics.median(pnls), 4) if pnls else None,
            "exits": exits,
        })
    out.sort(key=lambda r: r["pnl"])
    return out


def bucket_outcomes(markets: list[dict]) -> dict:
    out = {"win": 0, "loss": 0, "pending": 0, "no_position": 0, "other": 0}
    for m in markets:
        pos = m.get("position")
        ro = m.get("resolved_outcome")
        if not pos:
            if ro == "no_position" or m.get("resolved"):
                out["no_position"] += 1
            continue
        if ro == "win":
            out["win"] += 1
        elif ro == "loss":
            out["loss"] += 1
        elif ro in (None, "pending") or not m.get("resolved"):
            out["pending"] += 1
        else:
            out["other"] += 1
    return out


def hold_vs_exit(markets: list[dict]) -> dict:
    annotated = 0
    exit_sum = 0.0
    hold_sum = 0.0
    for m in markets:
        pos = m.get("position")
        hold = _f(m.get("hold_to_resolution_pnl"))
        if pos and pos.get("status") == "closed" and hold is not None:
            annotated += 1
            exit_sum += _f(pos.get("pnl"), 0.0) or 0.0
            hold_sum += hold
    return {
        "annotated": annotated,
        "exit_pnl_sum": round(exit_sum, 2),
        "hold_pnl_sum": round(hold_sum, 2),
        "hold_minus_exit": round(hold_sum - exit_sum, 2),
    }


def build_dashboard(data_dir: Path) -> dict:
    """Full payload for GET /api/dashboard."""
    data_dir = Path(data_dir)
    markets = load_markets(data_dir)
    state = load_state(data_dir)
    cal = load_calibration(data_dir)
    trades = flatten_trades(markets)

    starting = _f(state.get("starting_balance"), 10000.0) or 10000.0
    bal = balance_from_markets(markets, starting)
    open_cap = _open_capital(markets)
    realized = round(sum(
        (_f(t.get("pnl"), 0.0) or 0.0)
        for t in trades if t.get("position_status") == "closed"
    ), 2)
    n_open = sum(1 for t in trades if t.get("position_status") == "open")
    n_closed = sum(1 for t in trades if t.get("position_status") == "closed")
    equity = round(bal["balance"] + open_cap, 2)
    return_pct = round((equity - starting) / starting * 100, 2) if starting else 0.0

    peak = _f(state.get("peak_balance"), starting) or starting
    cash = bal["balance"]
    drawdown_pct = round((peak - cash) / peak * 100, 2) if peak else 0.0

    actuals_count = sum(1 for m in markets if m.get("actual_temp") is not None)

    # Calibration rows for table
    cal_rows = []
    for key, val in sorted(cal.items()):
        if not isinstance(val, dict):
            continue
        cal_rows.append({
            "key": key,
            "sigma": _f(val.get("sigma")),
            "bias": _f(val.get("bias")),
            "n": val.get("n"),
        })

    state_mismatch = None
    if state:
        sb = _f(state.get("balance"))
        if sb is not None and abs(sb - bal["balance"]) > 0.02:
            state_mismatch = {
                "state_balance": sb,
                "markets_balance": bal["balance"],
                "delta": round(sb - bal["balance"], 2),
            }

    return {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "data_dir": str(data_dir.resolve()),
        "summary": {
            "balance": bal["balance"],
            "starting_balance": starting,
            "peak_balance": peak,
            "equity": equity,
            "open_capital": open_cap,
            "realized_pnl": realized,
            "return_pct": return_pct,
            "drawdown_pct": drawdown_pct,
            "open_count": n_open,
            "closed_count": n_closed,
            "total_trades": n_open + n_closed,
            "wins": int(state.get("wins") or 0),
            "losses": int(state.get("losses") or 0),
            "actuals_count": actuals_count,
            "markets_count": len(markets),
            "updated_at": state.get("updated_at"),
            "state_balance": _f(state.get("balance")),
            "state_equity": _f(state.get("equity")),
            "state_realized_pnl": _f(state.get("realized_pnl")),
            "state_mismatch": state_mismatch,
            "exits": exit_breakdown(trades),
            "bucket_outcomes": bucket_outcomes(markets),
            "hold_vs_exit": hold_vs_exit(markets),
        },
        "trades": trades,
        "cities": city_stats(markets),
        "sources": {
            "accuracy": source_accuracy(markets),
            "trade_pnl": source_trade_pnl(trades),
            "calibration": cal_rows,
        },
        "series": {
            "cumulative_pnl": cumulative_pnl_series(trades),
        },
    }


def market_detail(data_dir: Path, city: str, date: str) -> dict | None:
    path = Path(data_dir) / "markets" / f"{city}_{date}.json"
    if not path.is_file():
        return None
    try:
        m = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None

    snaps = m.get("forecast_snapshots") or []
    source_keys = set()
    for s in snaps:
        source_keys.update(_source_keys_in_snap(s))
    source_keys = sorted(source_keys)

    forecast_series = {
        "ts": [s.get("ts") for s in snaps],
        "best": [_f(s.get("best")) for s in snaps],
        "sources": {
            k: [_f(s.get(k)) for s in snaps] for k in source_keys
        },
        "hours_left": [_f(s.get("hours_left")) for s in snaps],
    }
    mkt_snaps = m.get("market_snapshots") or []
    price_series = {
        "ts": [s.get("ts") for s in mkt_snaps],
        "top_price": [_f(s.get("top_price")) for s in mkt_snaps],
        "top_bucket": [s.get("top_bucket") for s in mkt_snaps],
    }

    return {
        "city": m.get("city"),
        "city_name": m.get("city_name"),
        "date": m.get("date"),
        "unit": m.get("unit"),
        "station": m.get("station"),
        "status": m.get("status"),
        "actual_temp": _f(m.get("actual_temp")),
        "resolved": m.get("resolved"),
        "resolved_outcome": m.get("resolved_outcome"),
        "held_to_resolution": m.get("held_to_resolution"),
        "hold_to_resolution_pnl": _f(m.get("hold_to_resolution_pnl")),
        "pnl": _f(m.get("pnl")),
        "position": m.get("position"),
        "all_outcomes": m.get("all_outcomes") or [],
        "forecast_series": forecast_series,
        "price_series": price_series,
        "source_keys": source_keys,
        "event_end_date": m.get("event_end_date"),
        "hours_at_discovery": _f(m.get("hours_at_discovery")),
        "created_at": m.get("created_at"),
    }
