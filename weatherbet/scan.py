"""Full scan, dry-run preview, open/close/resolve cycle."""
import time
from datetime import datetime, timezone, timedelta

import requests

from weatherbet import config
from weatherbet import calibration
from weatherbet.calibration import get_sigma, run_calibration
from weatherbet.model import compute_stop_price
from weatherbet.forecasts import take_forecast_snapshot, get_actual_temp
from weatherbet.polymarket import (
    get_polymarket_event, parse_event_outcomes, hours_to_resolution,
    in_bucket, check_market_resolved,
)
from weatherbet.storage import (
    load_market, save_market, new_market, load_all_markets,
)
from weatherbet.state import load_state, refresh_state_stats
from weatherbet.risk import (
    portfolio_snapshot, book_register_open, book_register_close,
)
from weatherbet.entry import consider_entry, _fmt_bucket, _fmt_temp


def scan_preview():
    """
    Dry-run scan: fetch forecasts + markets, report findings and would-be
    entries. Does not open/close positions, resolve, write market files, or
    change balance.
    """
    now = datetime.now(timezone.utc)
    state = load_state()
    balance = state["balance"]
    # Virtual book for risk-cap preview only (not persisted)
    book = portfolio_snapshot(load_all_markets())

    found = 0
    would_buys = []
    skip_counts = {}

    print(f"  Paper balance (unchanged): ${balance:,.2f}")
    print(f"  Open positions (book):     {book['total']} | "
          f"capital at risk ${book['capital']:,.2f}")
    print(f"  Filters: min_ev={config.MIN_EV} "
          f"price=[{config.MIN_PRICE},{config.MAX_PRICE}) "
          f"min_vol={config.MIN_VOLUME} hours=[{config.MIN_HOURS},{config.MAX_HOURS}] "
          f"max_bet=${config.MAX_BET} max_slip={config.MAX_SLIPPAGE} "
          f"min_depth=${config.MIN_ASK_DEPTH_USD} "
          f"stop=max({config.STOP_LOSS_PCT:.0%},{config.MIN_STOP_WIDTH})")
    print()

    for city_slug, loc in config.LOCATIONS.items():
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']} ({loc['station']})...", flush=True)

        try:
            dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d")
                     for i in range(4)]
            snapshots = take_forecast_snapshot(city_slug, dates)
            time.sleep(0.3)
        except Exception as e:
            print(f"     skipped ({e})")
            continue

        city_hits = 0
        for i, date in enumerate(dates):
            dt = datetime.strptime(date, "%Y-%m-%d")
            event = get_polymarket_event(
                city_slug, config.MONTHS[dt.month - 1], dt.day, dt.year)
            if not event:
                continue

            end_date = event.get("endDate", "")
            hours = hours_to_resolution(end_date) if end_date else 0
            horizon = f"D+{i}"
            outcomes = parse_event_outcomes(event)
            snap = snapshots.get(date, {})
            forecast_temp = snap.get("best")
            best_source = snap.get("best_source")

            found += 1
            city_hits += 1

            # Read-only look at existing paper state
            mkt = load_market(city_slug, date)
            pos = (mkt or {}).get("position")
            pos_status = (pos or {}).get("status")

            src = (best_source or "?").upper()
            fc_bits = (
                f"best {_fmt_temp(forecast_temp, unit_sym)} ({src})"
                f" | ECMWF {_fmt_temp(snap.get('ecmwf'), unit_sym)}"
                f" HRRR {_fmt_temp(snap.get('hrrr'), unit_sym)}"
                f" METAR {_fmt_temp(snap.get('metar'), unit_sym)}"
            )
            print(f"     {horizon} {date} | {hours:.1f}h left | {fc_bits}")
            print(f"       buckets: {len(outcomes)} | "
                  f"event end {end_date or '—'}")

            # Matched bucket info (even if we will not trade)
            matched = None
            if forecast_temp is not None:
                for o in outcomes:
                    if in_bucket(forecast_temp, o["range"][0], o["range"][1]):
                        matched = o
                        break
            if matched:
                t_low, t_high = matched["range"]
                yes_p = matched.get("yes_price", matched.get("bid"))
                no_p = matched.get("no_price", matched.get("ask"))
                print(
                    f"       match {_fmt_bucket(t_low, t_high, unit_sym)} | "
                    f"yes ${yes_p:.3f} no ${no_p:.3f} "
                    f"(outcomePrices, not CLOB) | "
                    f"vol {matched['volume']:.0f}"
                )
            else:
                print("       match — (forecast not in any bucket)")

            if mkt and mkt.get("status") == "resolved":
                print("       [HOLD] market already resolved on disk")
                skip_counts["resolved"] = skip_counts.get("resolved", 0) + 1
                continue
            if pos_status == "open":
                pl = pos.get("bucket_low")
                ph = pos.get("bucket_high")
                print(
                    f"       [HOLD] open paper pos "
                    f"{_fmt_bucket(pl, ph, unit_sym)} @ "
                    f"${pos.get('entry_price', 0):.3f} "
                    f"(${pos.get('cost', 0):.2f})"
                )
                skip_counts["already_open"] = skip_counts.get(
                    "already_open", 0) + 1
                continue
            if pos is not None:
                print(
                    f"       [HOLD] prior position on file "
                    f"(status={pos_status}) — no re-entry"
                )
                skip_counts["prior_position"] = skip_counts.get(
                    "prior_position", 0) + 1
                continue

            signal, reason = consider_entry(
                city_slug,
                date,
                outcomes,
                forecast_temp,
                best_source,
                hours,
                balance,
                book,
                opened_at=snap.get("ts"),
                fetch_live_book=True,
            )
            if signal:
                bucket_label = _fmt_bucket(
                    signal["bucket_low"], signal["bucket_high"], unit_sym)
                spr = signal.get("spread")
                spr_s = f"${spr:.3f}" if spr is not None else "—"
                print(
                    f"       [WOULD BUY] {bucket_label} | "
                    f"CLOB bid ${signal['bid_at_entry']:.3f} "
                    f"ask ${signal['entry_price']:.3f} "
                    f"spr {spr_s} | "
                    f"EV {signal['ev']:+.2f} | p={signal['p']:.2f} | "
                    f"${signal['cost']:.2f} ({signal['shares']} sh) | "
                    f"{(signal['forecast_src'] or '?').upper()}"
                )
                print(
                    f"                paper fill assumes full ${signal['cost']:.2f} "
                    f"at bestAsk (no depth check)"
                )
                would_buys.append({
                    "city": loc["name"],
                    "city_slug": city_slug,
                    "date": date,
                    "horizon": horizon,
                    "hours": round(hours, 1),
                    "bucket": bucket_label,
                    "signal": signal,
                })
                # Virtual fill so later rows respect risk caps / bankroll
                balance -= signal["cost"]
                book_register_open(
                    book, city_slug, date, signal["cost"])
            else:
                print(f"       [SKIP] {reason}")
                key = reason.split(":")[0].split("<")[0].strip()
                if len(key) > 40:
                    key = key[:40]
                skip_counts[key] = skip_counts.get(key, 0) + 1

            time.sleep(0.1)

        if city_hits == 0:
            print("     (no Polymarket events in next 4 days)")

    # --- Summary ---
    print(f"\n{'='*55}")
    print(f"  SCAN PREVIEW SUMMARY (dry-run — nothing filled)")
    print(f"{'='*55}")
    print(f"  Markets found:     {found}")
    print(f"  Would open:        {len(would_buys)}")
    if skip_counts:
        print(f"  Skip breakdown:")
        for k, n in sorted(skip_counts.items(), key=lambda x: -x[1]):
            print(f"    {n:3d}  {k}")

    if would_buys:
        total_cost = sum(w["signal"]["cost"] for w in would_buys)
        print(f"\n  Hypothetical new positions (${total_cost:.2f} total):")
        for w in would_buys:
            s = w["signal"]
            print(
                f"    {w['city']:<16} {w['horizon']} {w['date']} | "
                f"{w['bucket']:<12} | ${s['entry_price']:.3f} | "
                f"EV {s['ev']:+.2f} | ${s['cost']:.2f} | "
                f"{(s['forecast_src'] or '?').upper()}"
            )
        print(
            f"\n  Virtual balance after would-buys: ${balance:,.2f} "
            f"(not saved)"
        )
    else:
        print("\n  No new positions would be opened under current filters.")

    print(f"{'='*55}\n")
    return found, len(would_buys)

def scan_and_update():
    """Main function of one cycle: updates forecasts, opens/closes positions."""
    now = datetime.now(timezone.utc)
    state = load_state()
    balance = state["balance"]
    new_pos = 0
    closed = 0
    resolved = 0
    # Live portfolio book for risk caps (updated as we open/close in this scan)
    book = portfolio_snapshot(load_all_markets())

    for city_slug, loc in config.LOCATIONS.items():
        unit = loc["unit"]
        unit_sym = "F" if unit == "F" else "C"
        print(f"  -> {loc['name']}...", end=" ", flush=True)

        try:
            dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d")
                     for i in range(4)]
            snapshots = take_forecast_snapshot(city_slug, dates)
            time.sleep(0.3)
        except Exception as e:
            print(f"skipped ({e})")
            continue

        for i, date in enumerate(dates):
            dt = datetime.strptime(date, "%Y-%m-%d")
            event = get_polymarket_event(
                city_slug, config.MONTHS[dt.month - 1], dt.day, dt.year)
            if not event:
                continue

            end_date = event.get("endDate", "")
            hours = hours_to_resolution(end_date) if end_date else 0
            horizon = f"D+{i}"

            # Load or create market record
            mkt = load_market(city_slug, date)
            if mkt is None:
                if hours < config.MIN_HOURS or hours > config.MAX_HOURS:
                    continue
                mkt = new_market(city_slug, date, event, hours)

            # Skip if market already resolved
            if mkt["status"] == "resolved":
                continue

            # Update outcomes list — prices taken directly from event
            outcomes = parse_event_outcomes(event)
            mkt["all_outcomes"] = outcomes

            # Forecast snapshot
            snap = snapshots.get(date, {})
            forecast_snap = {
                "ts":          snap.get("ts"),
                "horizon":     horizon,
                "hours_left":  round(hours, 1),
                "ecmwf":       snap.get("ecmwf"),
                "hrrr":        snap.get("hrrr"),
                "metar":       snap.get("metar"),
                "best":        snap.get("best"),
                "best_source": snap.get("best_source"),
            }
            mkt["forecast_snapshots"].append(forecast_snap)

            # Market price snapshot
            top = max(outcomes, key=lambda x: x["price"]) if outcomes else None
            market_snap = {
                "ts":       snap.get("ts"),
                "top_bucket": f"{top['range'][0]}-{top['range'][1]}{unit_sym}" if top else None,
                "top_price":  top["price"] if top else None,
            }
            mkt["market_snapshots"].append(market_snap)

            forecast_temp = snap.get("best")
            best_source = snap.get("best_source")

            # --- STOP-LOSS AND TRAILING STOP ---
            if mkt.get("position") and mkt["position"].get("status") == "open":
                pos = mkt["position"]
                current_price = None
                for o in outcomes:
                    if o["market_id"] == pos["market_id"]:
                        current_price = o["price"]
                        break

                if current_price is not None:
                    current_price = o.get("bid", current_price)  # sell at bid
                    entry = pos["entry_price"]
                    stop = pos.get("stop_price")
                    if stop is None:
                        stop = compute_stop_price(entry)

                    # Trailing: if up 20%+ — move stop to breakeven
                    if current_price >= entry * 1.20 and stop < entry:
                        pos["stop_price"] = entry
                        pos["trailing_activated"] = True
                        stop = entry

                    # Check stop
                    if current_price <= stop:
                        pnl = round((current_price - entry) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        book_register_close(book, city_slug, date, pos["cost"])
                        pos["closed_at"] = snap.get("ts")
                        pos["close_reason"] = "stop_loss" if current_price < entry else "trailing_stop"
                        pos["exit_price"] = current_price
                        pos["pnl"] = pnl
                        pos["status"] = "closed"
                        closed += 1
                        reason = "STOP" if current_price < entry else "TRAILING BE"
                        print(
                            f"  [{reason}] {loc['name']} {date} | entry ${entry:.3f} exit ${current_price:.3f} | PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")

            # --- CLOSE POSITION if forecast shifted 2+ degrees ---
            # Must require status=="open". Without it, every later scan re-credits
            # cost+pnl for already-closed positions (state.json balance inflation).
            if mkt.get("position") and mkt["position"].get("status") == "open" and forecast_temp is not None:
                pos = mkt["position"]
                old_bucket_low = pos["bucket_low"]
                old_bucket_high = pos["bucket_high"]
                # 2-degree buffer — avoid closing on small forecast fluctuations
                unit = loc["unit"]
                buffer = 2.0 if unit == "F" else 1.0
                mid_bucket = (old_bucket_low + old_bucket_high) / 2 if old_bucket_low != - \
                    999 and old_bucket_high != 999 else forecast_temp
                forecast_far = abs(
                    forecast_temp - mid_bucket) > (abs(mid_bucket - old_bucket_low) + buffer)
                if not in_bucket(forecast_temp, old_bucket_low, old_bucket_high) and forecast_far:
                    current_price = None
                    for o in outcomes:
                        if o["market_id"] == pos["market_id"]:
                            current_price = o["price"]
                            break
                    if current_price is not None:
                        pnl = round(
                            (current_price - pos["entry_price"]) * pos["shares"], 2)
                        balance += pos["cost"] + pnl
                        book_register_close(book, city_slug, date, pos["cost"])
                        mkt["position"]["closed_at"] = snap.get("ts")
                        mkt["position"]["close_reason"] = "forecast_changed"
                        mkt["position"]["exit_price"] = current_price
                        mkt["position"]["pnl"] = pnl
                        mkt["position"]["status"] = "closed"
                        closed += 1
                        print(
                            f"  [CLOSE] {loc['name']} {date} — forecast changed | PnL: {'+'if pnl >= 0 else ''}{pnl:.2f}")

            # --- OPEN POSITION ---
            # One position per market record (closed position blocks re-entry).
            if not mkt.get("position") and forecast_temp is not None and hours >= config.MIN_HOURS:
                best_signal, skip_reason = consider_entry(
                    city_slug,
                    date,
                    outcomes,
                    forecast_temp,
                    best_source,
                    hours,
                    balance,
                    book,
                    opened_at=snap.get("ts"),
                    fetch_live_book=True,
                )
                if best_signal:
                    balance -= best_signal["cost"]
                    book_register_open(
                        book, city_slug, date, best_signal["cost"])
                    mkt["position"] = best_signal
                    state["total_trades"] += 1
                    new_pos += 1
                    bucket_label = _fmt_bucket(
                        best_signal["bucket_low"],
                        best_signal["bucket_high"],
                        unit_sym,
                    )
                    src = (best_signal["forecast_src"] or "?").upper()
                    print(f"  [BUY]  {loc['name']} {horizon} {date} | {bucket_label} | "
                          f"${best_signal['entry_price']:.3f} | EV {best_signal['ev']:+.2f} | "
                          f"${best_signal['cost']:.2f} ({src})")
                elif skip_reason:
                    if skip_reason.startswith("risk:"):
                        print(
                            f"  [RISK] {loc['name']} {date} — skip: "
                            f"{skip_reason[len('risk:'):].strip()}")
                    elif skip_reason.startswith("real ask") or skip_reason.startswith("ask $"):
                        print(
                            f"  [SKIP] {loc['name']} {date} — {skip_reason}")

            # Market closed by time
            if hours < 0.5 and mkt["status"] == "open":
                mkt["status"] = "closed"

            save_market(mkt)
            time.sleep(0.1)

        print("ok")

    # --- RESOLUTION + ACTUALS ---
    # 1) Open positions held to Polymarket close → settle bankroll + outcome
    # 2) Early-exited positions → still record resolved_outcome (counterfactual
    #    "did our bucket win?") without touching balance
    # 3) Past dates → backfill station actual_temp for residual calibration
    today_str = now.strftime("%Y-%m-%d")
    outcome_backfill = 0

    for mkt in load_all_markets():
        pos = mkt.get("position")
        market_id = (pos or {}).get("market_id")
        dirty = False

        # --- Polymarket bucket outcome ---
        if market_id and mkt.get("resolved_outcome") is None:
            won = check_market_resolved(market_id)
            if won is not None:
                mkt["resolved_outcome"] = "win" if won else "loss"
                mkt["resolved"] = True
                mkt["status"] = "resolved"
                dirty = True

                price = pos["entry_price"]
                size = pos["cost"]
                shares = pos["shares"]
                hold_pnl = round(
                    shares * (1 - price), 2) if won else round(-size, 2)
                # What PnL would have been if held to $0/$1 resolution
                mkt["hold_to_resolution_pnl"] = hold_pnl

                if pos.get("status") == "open":
                    # Still open at settlement → credit bankroll
                    balance += size + hold_pnl
                    book_register_close(book, mkt["city"], mkt["date"], size)
                    pos["exit_price"] = 1.0 if won else 0.0
                    pos["pnl"] = hold_pnl
                    pos["close_reason"] = "resolved"
                    pos["closed_at"] = now.isoformat()
                    pos["status"] = "closed"
                    mkt["pnl"] = hold_pnl
                    mkt["held_to_resolution"] = True
                    if won:
                        state["wins"] += 1
                    else:
                        state["losses"] += 1
                    result = "WIN" if won else "LOSS"
                    print(
                        f"  [{result}] {mkt['city_name']} {mkt['date']} | "
                        f"held | PnL: {'+' if hold_pnl >= 0 else ''}{hold_pnl:.2f}")
                    resolved += 1
                else:
                    # Already exited (TP/stop/forecast) — annotate only
                    mkt["held_to_resolution"] = False
                    exit_pnl = pos.get("pnl")
                    exit_str = (
                        f"exit PnL {'+' if exit_pnl >= 0 else ''}{exit_pnl:.2f}"
                        if exit_pnl is not None else "exit PnL n/a"
                    )
                    result = "BUCKET WIN" if won else "BUCKET LOSS"
                    print(
                        f"  [{result}] {mkt['city_name']} {mkt['date']} | "
                        f"exited early ({pos.get('close_reason')}) | "
                        f"{exit_str} | hold would be "
                        f"{'+' if hold_pnl >= 0 else ''}{hold_pnl:.2f}")
                    outcome_backfill += 1

                time.sleep(0.3)

        # --- Station actual (residuals), once the calendar day is past ---
        if mkt.get("actual_temp") is None and mkt.get("date", today_str) < today_str:
            actual = get_actual_temp(mkt["city"], mkt["date"])
            if actual is not None:
                mkt["actual_temp"] = actual
                mkt["resolved"] = True
                dirty = True
                time.sleep(0.2)

        if dirty:
            save_market(mkt)

    if outcome_backfill:
        print(f"  [SETTLE] annotated {outcome_backfill} early-exit market outcome(s)")

    state["balance"] = round(balance, 2)
    state["peak_balance"] = max(state.get("peak_balance", balance), balance)
    # Persist cash + rebuild trade KPIs from market files (source of truth)
    all_mkts = load_all_markets()
    refresh_state_stats(state=state, markets=all_mkts, write=True)

    # Run calibration when enough markets have actuals
    cal_eligible = len([
        m for m in all_mkts
        if m.get("actual_temp") is not None
        and (m.get("status") == "resolved" or m.get("resolved"))
    ])
    if cal_eligible >= config.CALIBRATION_MIN:
        calibration._cal = run_calibration(all_mkts)

    return new_pos, closed, resolved
