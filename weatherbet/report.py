"""CLI status and full report."""
from weatherbet import config
from weatherbet.storage import load_all_markets
from weatherbet.state import (
    load_state, refresh_state_stats, reconcile_balance,
)


def print_status():
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
    markets = load_all_markets()
    resolved = [m for m in markets if m["status"]
                == "resolved" and m.get("pnl") is not None]

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — FULL REPORT")
    print(f"{'='*55}")

    if not resolved:
        print("  No resolved markets yet.")
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
