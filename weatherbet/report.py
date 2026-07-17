"""CLI status and full report (read-only analysis over market files)."""
from weatherbet import config
from weatherbet import calibration
from weatherbet.calibration import load_cal, get_sigma, get_bias
from weatherbet.model import bucket_prob, calc_ev
from weatherbet.polymarket import in_bucket
from weatherbet.storage import load_all_markets
from weatherbet.state import (
    load_state, refresh_state_stats, reconcile_balance,
)


def _last_forecast(mkt):
    """Latest snapshot best temp + source, or (None, None)."""
    snaps = mkt.get("forecast_snapshots") or []
    if not snaps:
        return None, None
    snap = snaps[-1]
    return snap.get("best"), snap.get("best_source") or "ecmwf"


def _matched_outcome(mkt, forecast_temp):
    if forecast_temp is None:
        return None
    for o in mkt.get("all_outcomes") or []:
        rng = o.get("range")
        if not rng or len(rng) != 2:
            continue
        if in_bucket(forecast_temp, rng[0], rng[1]):
            return o
    return None


def _yes_price(o):
    if not o:
        return None
    p = o.get("yes_price", o.get("price", o.get("bid")))
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if 0 < p < 1:
        return p
    return None


def model_vs_market_rows(markets=None):
    """
    Recompute partition model p for each market's latest forecast vs stored
    book snapshots. Pure reporting — does not open/close anything.

    Returns list of dicts (one per market with match + usable mid price).
    """
    if markets is None:
        markets = load_all_markets()

    rows = []
    for m in markets:
        forecast, src = _last_forecast(m)
        if forecast is None:
            continue
        matched = _matched_outcome(m, forecast)
        if not matched:
            continue
        t_low, t_high = matched["range"]
        price = _yes_price(matched)
        if price is None:
            continue

        sigma = get_sigma(m["city"], src)
        bias = get_bias(m["city"], src)
        p = bucket_prob(forecast, t_low, t_high, sigma, bias)
        ev = calc_ev(p, price)

        # Market favorite among stored outcomes
        fav = None
        fav_price = None
        for o in m.get("all_outcomes") or []:
            yp = _yes_price(o)
            if yp is None:
                continue
            if fav_price is None or yp > fav_price:
                fav_price = yp
                fav = o

        fav_range = tuple(fav["range"]) if fav and fav.get("range") else None
        matched_is_fav = (
            fav is not None
            and fav.get("market_id") == matched.get("market_id")
        )

        rows.append({
            "city": m["city"],
            "city_name": m.get("city_name", m["city"]),
            "date": m["date"],
            "unit": m.get("unit", "F"),
            "forecast": forecast,
            "source": src,
            "bucket_low": t_low,
            "bucket_high": t_high,
            "sigma": sigma,
            "bias": bias,
            "model_p": round(p, 4),
            "matched_price": price,
            "ev": ev,
            "fav_price": fav_price,
            "fav_range": fav_range,
            "matched_is_favorite": matched_is_fav,
            "status": m.get("status"),
            "has_position": bool(m.get("position")),
            "entry_p": (m.get("position") or {}).get("p"),
            "entry_price": (m.get("position") or {}).get("entry_price"),
            "entry_ev": (m.get("position") or {}).get("ev"),
        })
    return rows


def summarize_model_vs_market(rows, min_ev=None):
    """Aggregate counters for model-vs-market rows."""
    if min_ev is None:
        min_ev = config.MIN_EV
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "min_ev": min_ev,
        }

    ev_pass = sum(1 for r in rows if r["ev"] >= min_ev)
    ev_pos = sum(1 for r in rows if r["ev"] > 0)
    ev_neg = sum(1 for r in rows if r["ev"] <= 0)
    fav_match = sum(1 for r in rows if r["matched_is_favorite"])
    mean_p = sum(r["model_p"] for r in rows) / n
    mean_price = sum(r["matched_price"] for r in rows) / n
    mean_ev = sum(r["ev"] for r in rows) / n
    # Median EV — mean is dominated by sub-5¢ mids (p/price − 1 explodes)
    evs = sorted(r["ev"] for r in rows)
    mid = n // 2
    median_ev = evs[mid] if n % 2 else 0.5 * (evs[mid - 1] + evs[mid])
    # When our match is the market favorite: model mass vs favorite price
    fav_rows = [r for r in rows if r["matched_is_favorite"] and r["fav_price"]]
    mean_fav_gap = None
    if fav_rows:
        # positive gap => model more confident than market price
        mean_fav_gap = sum(
            r["model_p"] - r["fav_price"] for r in fav_rows
        ) / len(fav_rows)

    return {
        "n": n,
        "min_ev": min_ev,
        "ev_pass": ev_pass,
        "ev_pos": ev_pos,
        "ev_neg": ev_neg,
        "fav_match": fav_match,
        "mean_model_p": round(mean_p, 4),
        "mean_matched_price": round(mean_price, 4),
        "mean_ev": round(mean_ev, 4),
        "median_ev": round(median_ev, 4),
        "mean_model_minus_fav_price": (
            round(mean_fav_gap, 4) if mean_fav_gap is not None else None
        ),
        "n_fav_aligned": len(fav_rows),
    }


def _print_model_vs_market(markets, *, detail=False, top=8):
    """Print model mode mass vs book section (status compact / report detail)."""
    rows = model_vs_market_rows(markets)
    summary = summarize_model_vs_market(rows)

    print(f"\n  Model vs market (partition p, latest forecast snap):")
    if summary["n"] == 0:
        print("    (no markets with forecast + matched bucket + price)")
        return rows, summary

    print(
        f"    n={summary['n']}  mean p={summary['mean_model_p']:.3f}  "
        f"mean match mid={summary['mean_matched_price']:.3f}  "
        f"median EV={summary['median_ev']:+.3f}  "
        f"(mean EV={summary['mean_ev']:+.3f}, skewed by cheap mids)"
    )
    print(
        f"    EV≥min_ev({summary['min_ev']}): {summary['ev_pass']}/{summary['n']}  "
        f"EV>0: {summary['ev_pos']}  EV≤0: {summary['ev_neg']}  "
        f"match=favorite: {summary['fav_match']}/{summary['n']}"
    )
    if summary.get("mean_model_minus_fav_price") is not None:
        g = summary["mean_model_minus_fav_price"]
        print(
            f"    When match is favorite (n={summary['n_fav_aligned']}): "
            f"mean (model_p − fav_price) = {g:+.3f}  "
            f"({'model hotter' if g > 0 else 'market hotter' if g < 0 else 'flat'})"
        )

    # Entry-era note: legacy binary p=1 vs recompute
    with_entry = [r for r in rows if r.get("entry_p") is not None]
    if with_entry:
        legacy = sum(1 for r in with_entry if r["entry_p"] >= 0.999)
        print(
            f"    Positions with stored entry p: {len(with_entry)}  "
            f"(legacy p≈1: {legacy} — pre-partition fills)"
        )

    if detail and rows:
        # Highest positive EV and deepest negative for eyeballing
        ranked = sorted(rows, key=lambda r: r["ev"], reverse=True)
        print(f"\n    Top edge (by model EV):")
        for r in ranked[:top]:
            _print_mvm_line(r)
        print(f"\n    Worst edge (by model EV):")
        for r in ranked[-top:]:
            _print_mvm_line(r)

    return rows, summary


def _print_mvm_line(r):
    unit = "F" if r["unit"] == "F" else "C"
    lo, hi = r["bucket_low"], r["bucket_high"]
    if lo == -999:
        label = f"≤{hi}{unit}"
    elif hi == 999:
        label = f"≥{lo}{unit}"
    elif lo == hi:
        label = f"{lo}{unit}"
    else:
        label = f"{lo}-{hi}{unit}"
    fav = "★" if r["matched_is_favorite"] else " "
    print(
        f"      {fav} {r['city_name']:<14} {r['date']} | {label:<10} | "
        f"p={r['model_p']:.3f} mid={r['matched_price']:.3f} "
        f"EV={r['ev']:+.3f} | σ={r['sigma']:.2f} {r['source']}"
    )


def _print_calibration_summary():
    cal = load_cal()
    if not cal:
        print(f"\n  Calibration:  (none yet — defaults SIGMA_F={config.SIGMA_F} / "
              f"SIGMA_C={config.SIGMA_C})")
        return
    print(f"\n  Calibration:  {len(cal)} city/source keys")
    # Show a few tightest and widest
    items = []
    for k, v in cal.items():
        try:
            items.append((k, float(v.get("sigma", 0)), float(v.get("bias", 0) or 0),
                          int(v.get("n", 0))))
        except (TypeError, ValueError):
            continue
    if not items:
        return
    items.sort(key=lambda x: x[1])
    print("    tightest:", ", ".join(
        f"{k} σ={s:.2f} b={b:+.2f} n={n}" for k, s, b, n in items[:3]))
    print("    widest:  ", ", ".join(
        f"{k} σ={s:.2f} b={b:+.2f} n={n}" for k, s, b, n in items[-3:]))


def print_status():
    # Ensure get_sigma/get_bias see disk calibration for reporting
    calibration._cal = load_cal()

    state = load_state()
    markets = load_all_markets()
    # Rebuild summary KPIs from markets; keep cash fields as stored
    state = refresh_state_stats(state=state, markets=markets, write=True)

    open_pos = [m for m in markets if m.get(
        "position") and m["position"].get("status") == "open"]

    bal = state["balance"]
    start = state["starting_balance"]
    peak = state.get("peak_balance", bal)
    equity = state.get("equity", bal)
    ret_pct = state.get("return_pct", 0.0)
    dd_pct = state.get("drawdown_pct", 0.0)
    wins = state.get("wins", 0)
    losses = state.get("losses", 0)
    held_n = wins + losses
    closed_n = state.get("closed_count", 0)
    open_n = state.get("open_count", 0)
    realized = state.get("realized_pnl", 0.0)
    exits = state.get("exits") or {}
    buckets = state.get("bucket_outcomes") or {}
    hv = state.get("hold_vs_exit") or {}

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STATUS")
    print(f"{'='*55}")
    print(
        f"  Cash:        ${bal:,.2f}  (start ${start:,.2f}, peak ${peak:,.2f})")
    print(
        f"  Equity:      ${equity:,.2f}  (cash + ${state.get('open_capital', 0):,.2f} open)  "
        f"{'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%  DD {dd_pct:.2f}%")
    recon = reconcile_balance(apply=False, markets=markets, state=state)
    if not recon["ok"]:
        print(
            f"  Balance check: DRIFT ${recon['delta']:+,.2f} vs market files "
            f"(true ${recon['true_balance']:,.2f}) — run: python weatherbet.py reconcile --fix")
    print(
        f"  Realized:    {'+' if realized >= 0 else ''}{realized:.2f}  "
        f"on {closed_n} closed | open {open_n} | total {state.get('total_trades', 0)}")
    if held_n:
        print(
            f"  Held→resolve: W {wins} / L {losses}  WR {wins/held_n:.0%}")
    else:
        print(f"  Held→resolve: none yet (wins/losses only count full holds)")
    bw, bl, bp = buckets.get("win", 0), buckets.get("loss", 0), buckets.get("pending", 0)
    print(f"  Bucket out:  win {bw} / loss {bl} / pending {bp}  "
          f"(includes early exits once annotated)")
    if exits:
        parts = [
            f"{r} {v['n']} ({'+' if v['pnl'] >= 0 else ''}{v['pnl']:.2f})"
            for r, v in sorted(exits.items(), key=lambda x: -x[1]["n"])
        ]
        print(f"  Exits:       {', '.join(parts)}")
    if hv.get("annotated"):
        d = hv.get("hold_minus_exit", 0)
        print(
            f"  Hold vs exit: n={hv['annotated']}  exit {hv.get('exit_pnl_sum', 0):+.2f}  "
            f"hold {hv.get('hold_pnl_sum', 0):+.2f}  "
            f"Δhold-exit {d:+.2f}  ({'hold better' if d > 0 else 'exit better' if d < 0 else 'flat'})")
    print(f"  Actuals:     {state.get('actuals_count', 0)} markets with station temp")

    _print_calibration_summary()
    _print_model_vs_market(markets, detail=False)

    if open_pos:
        print(f"\n  Open positions:")
        total_unrealized = 0.0
        for m in open_pos:
            pos = m["position"]
            unit_sym = "F" if m["unit"] == "F" else "C"
            label = f"{pos['bucket_low']}-{pos['bucket_high']}{unit_sym}"

            # Current price from latest market snapshot
            current_price = pos["entry_price"]
            snaps = m.get("market_snapshots", [])
            if snaps:
                # Find our bucket price in all_outcomes
                for o in m.get("all_outcomes", []):
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

            unrealized = round(
                (current_price - pos["entry_price"]) * pos["shares"], 2)
            total_unrealized += unrealized
            pnl_str = f"{'+'if unrealized >= 0 else ''}{unrealized:.2f}"

            print(f"    {m['city_name']:<16} {m['date']} | {label:<14} | "
                  f"entry ${pos['entry_price']:.3f} -> ${current_price:.3f} | "
                  f"PnL: {pnl_str} | {pos['forecast_src'].upper()}")

        sign = "+" if total_unrealized >= 0 else ""
        print(f"\n  Unrealized PnL: {sign}{total_unrealized:.2f}")

    print(f"{'='*55}\n")


def print_report():
    calibration._cal = load_cal()
    markets = load_all_markets()
    resolved = [m for m in markets if m["status"]
                == "resolved" and m.get("pnl") is not None]

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — FULL REPORT")
    print(f"{'='*55}")

    _print_calibration_summary()
    _print_model_vs_market(markets, detail=True, top=8)

    if not resolved:
        print("\n  No resolved markets yet (held-to-resolution PnL).")
        print(f"{'='*55}\n")
        return

    total_pnl = sum(m["pnl"] for m in resolved)
    wins = [m for m in resolved if m["resolved_outcome"] == "win"]
    losses = [m for m in resolved if m["resolved_outcome"] == "loss"]

    print(f"\n  Total resolved: {len(resolved)}")
    print(f"  Wins:           {len(wins)} | Losses: {len(losses)}")
    print(f"  Win rate:       {len(wins)/len(resolved):.0%}")
    print(f"  Total PnL:      {'+'if total_pnl >= 0 else ''}{total_pnl:.2f}")

    print(f"\n  By city:")
    for city in sorted(set(m["city"] for m in resolved)):
        group = [m for m in resolved if m["city"] == city]
        w = len([m for m in group if m["resolved_outcome"] == "win"])
        pnl = sum(m["pnl"] for m in group)
        name = config.LOCATIONS[city]["name"]
        print(
            f"    {name:<16} {w}/{len(group)} ({w/len(group):.0%})  PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")

    print(f"\n  Market details:")
    for m in sorted(resolved, key=lambda x: x["date"]):
        pos = m.get("position", {})
        unit_sym = "F" if m["unit"] == "F" else "C"
        snaps = m.get("forecast_snapshots", [])
        first_fc = snaps[0]["best"] if snaps else None
        last_fc = snaps[-1]["best"] if snaps else None
        label = f"{pos.get('bucket_low')}-{pos.get('bucket_high')}{unit_sym}" if pos else "no position"
        result = m["resolved_outcome"].upper()
        pnl_str = f"{'+'if m['pnl'] >= 0 else ''}{m['pnl']:.2f}" if m["pnl"] is not None else "-"
        fc_str = f"forecast {first_fc}->{last_fc}{unit_sym}" if first_fc else "no forecast"
        actual = f"actual {m['actual_temp']}{unit_sym}" if m["actual_temp"] else ""
        print(
            f"    {m['city_name']:<16} {m['date']} | {label:<14} | {fc_str} | {actual} | {result} {pnl_str}")

    print(f"{'='*55}\n")
