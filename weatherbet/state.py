"""Paper bankroll state.json and portfolio KPIs."""
import json
from datetime import datetime, timezone

from weatherbet import config
from weatherbet.storage import load_all_markets


def default_state():
    """Fresh paper-bankroll state (cash fields + portfolio summary placeholders)."""
    return {
        "balance":          config.BALANCE,
        "starting_balance": config.BALANCE,
        "peak_balance":     config.BALANCE,
        "total_trades":     0,
        "wins":             0,   # held-to-resolution only
        "losses":           0,   # held-to-resolution only
        # Filled by refresh_state_stats from market files:
        "updated_at":       None,
        "realized_pnl":     0.0,
        "closed_count":     0,
        "open_count":       0,
        "open_capital":     0.0,
        "equity":           config.BALANCE,
        "return_pct":       0.0,
        "drawdown_pct":     0.0,
        "exits":            {},
        "bucket_outcomes":  {"win": 0, "loss": 0, "pending": 0},
        "hold_vs_exit":     {
            "annotated": 0,
            "exit_pnl_sum": 0.0,
            "hold_pnl_sum": 0.0,
            "hold_minus_exit": 0.0,
        },
        "actuals_count":    0,
    }

def load_state():
    if config.STATE_FILE.exists():
        state = json.loads(config.STATE_FILE.read_text(encoding="utf-8"))
        # Backfill keys missing from older state.json files
        base = default_state()
        for k, v in base.items():
            if k not in state:
                state[k] = v
        return state
    return default_state()

def save_state(state):
    config.STATE_FILE.write_text(json.dumps(
        state, indent=2, ensure_ascii=False), encoding="utf-8")

def balance_from_markets(markets, starting_balance):
    """
    Ground-truth paper cash from market files.

    Open position: cost still locked → cash reduced by cost.
    Closed position: cost returned ± realized pnl.
    """
    total_cost = 0.0
    total_returned = 0.0
    n_open = 0
    n_closed = 0
    for m in markets:
        pos = m.get("position")
        if not pos:
            continue
        cost = float(pos.get("cost") or 0.0)
        total_cost += cost
        if pos.get("status") == "closed":
            n_closed += 1
            pnl = pos.get("pnl")
            total_returned += cost + (float(pnl) if pnl is not None else 0.0)
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

def compute_portfolio_stats(markets, starting_balance, balance, peak_balance):
    """
    Derive portfolio KPIs from market files + current cash/peak.

    Market files are source of truth for trades; balance/peak come from state.
    """
    start = float(starting_balance)
    bal = float(balance)
    peak = float(peak_balance) if peak_balance else start

    n_open = 0
    n_closed = 0
    open_capital = 0.0
    realized_pnl = 0.0
    exits = {}
    bucket_win = bucket_loss = bucket_pending = 0
    held_wins = held_losses = 0
    hv_n = 0
    hv_exit = 0.0
    hv_hold = 0.0
    actuals = 0

    for m in markets:
        if m.get("actual_temp") is not None:
            actuals += 1
        pos = m.get("position")
        if not pos:
            continue

        cost = float(pos.get("cost") or 0.0)
        status = pos.get("status")
        outcome = m.get("resolved_outcome")

        if status == "closed":
            n_closed += 1
            pnl = float(pos.get("pnl") or 0.0)
            realized_pnl += pnl
            reason = pos.get("close_reason") or "unknown"
            slot = exits.setdefault(reason, {"n": 0, "pnl": 0.0})
            slot["n"] += 1
            slot["pnl"] = round(slot["pnl"] + pnl, 2)

            if outcome == "win":
                bucket_win += 1
            elif outcome == "loss":
                bucket_loss += 1
            else:
                bucket_pending += 1

            # Held-to-resolution settlements (bankroll path)
            if (m.get("held_to_resolution") is True
                    or pos.get("close_reason") == "resolved"):
                if outcome == "win":
                    held_wins += 1
                elif outcome == "loss":
                    held_losses += 1

            # Counterfactual: early exit vs hold (needs annotation)
            hold_pnl = m.get("hold_to_resolution_pnl")
            if (hold_pnl is not None and outcome in ("win", "loss")
                    and pos.get("close_reason") != "resolved"):
                hv_n += 1
                hv_exit += pnl
                hv_hold += float(hold_pnl)
        else:
            n_open += 1
            open_capital += cost
            if outcome is None:
                bucket_pending += 1
            elif outcome == "win":
                bucket_win += 1
            elif outcome == "loss":
                bucket_loss += 1

    equity = round(bal + open_capital, 2)
    ret_pct = round((equity - start) / start * 100, 2) if start else 0.0
    dd_pct = 0.0
    if peak > 0:
        dd_pct = round(max(0.0, (peak - bal) / peak * 100), 2)

    # Round exit pnls
    exits_out = {
        k: {"n": v["n"], "pnl": round(v["pnl"], 2)}
        for k, v in sorted(exits.items())
    }

    return {
        "total_trades": n_open + n_closed,
        "wins": held_wins,
        "losses": held_losses,
        "realized_pnl": round(realized_pnl, 2),
        "closed_count": n_closed,
        "open_count": n_open,
        "open_capital": round(open_capital, 2),
        "equity": equity,
        "return_pct": ret_pct,
        "drawdown_pct": dd_pct,
        "exits": exits_out,
        "bucket_outcomes": {
            "win": bucket_win,
            "loss": bucket_loss,
            "pending": bucket_pending,
        },
        "hold_vs_exit": {
            "annotated": hv_n,
            "exit_pnl_sum": round(hv_exit, 2),
            "hold_pnl_sum": round(hv_hold, 2),
            "hold_minus_exit": round(hv_hold - hv_exit, 2),
        },
        "actuals_count": actuals,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

def refresh_state_stats(state=None, markets=None, write=True):
    """
    Recompute portfolio summary fields on state from market files.

    Does not change balance / starting_balance / peak_balance (cash ledger).
    total_trades / wins / losses are rebuilt from markets so they cannot drift.
    """
    if state is None:
        state = load_state()
    if markets is None:
        markets = load_all_markets()

    start = float(state.get("starting_balance", config.BALANCE))
    bal = float(state.get("balance", start))
    peak = float(state.get("peak_balance", bal))
    stats = compute_portfolio_stats(markets, start, bal, peak)

    for k, v in stats.items():
        state[k] = v

    if write:
        save_state(state)
    return state

def reconcile_balance(apply=False, markets=None, state=None):
    """
    Compare state.json balance to trade reconstruction from market files.

    If apply=True and they differ, rewrite balance (and lower peak_balance when
    it was only inflated by the bad cash figure). Always refreshes portfolio
    stats when apply=True. Returns a report dict.
    """
    if state is None:
        state = load_state()
    if markets is None:
        markets = load_all_markets()

    start = float(state.get("starting_balance", config.BALANCE))
    stored = round(float(state.get("balance", start)), 2)
    rebuilt = balance_from_markets(markets, start)
    true_bal = rebuilt["balance"]
    delta = round(stored - true_bal, 2)
    peak = float(state.get("peak_balance", stored))
    # True high-water mark is not recoverable after inflation; use a conservative
    # peak so drawdown is not fake-zero. Always peak >= true cash.
    peak_fixed = max(start, true_bal)

    report = {
        "stored_balance": stored,
        "true_balance": true_bal,
        "delta": delta,
        "ok": abs(delta) < 0.005,
        "peak_balance": peak,
        "peak_balance_fixed": round(peak_fixed, 2),
        "n_open": rebuilt["n_open"],
        "n_closed": rebuilt["n_closed"],
        "applied": False,
    }

    if apply and not report["ok"]:
        state["balance"] = true_bal
        state["peak_balance"] = round(peak_fixed, 2)
        report["applied"] = True
        report["peak_balance"] = float(state["peak_balance"])

    if apply:
        # Persist cash fix (if any) + full portfolio summary from markets
        refresh_state_stats(state=state, markets=markets, write=True)

    return report

def print_reconcile(apply=False):
    """CLI: show state vs market-file cash; optionally rewrite state.json."""
    report = reconcile_balance(apply=apply)
    print(f"\n{'='*55}")
    print(f"  WEATHERBET — config.BALANCE RECONCILE")
    print(f"{'='*55}")
    print(f"  Market files:  {report['n_open']} open | {report['n_closed']} closed")
    print(f"  state.json:    ${report['stored_balance']:,.2f}")
    print(f"  From trades:   ${report['true_balance']:,.2f}")
    print(f"  Delta:         {'+' if report['delta'] >= 0 else ''}"
          f"{report['delta']:,.2f}")
    if report["ok"]:
        print(f"  Status:        OK — balance matches market files")
        if apply:
            print(f"  Stats:         refreshed portfolio summary from markets")
    elif report["applied"]:
        print(f"  Status:        FIXED — wrote true balance to state.json")
        print(f"  peak_balance:  ${report['peak_balance']:,.2f}")
    else:
        print(f"  Status:        DRIFT — run with --fix to rewrite state.json")
        print(f"  peak_balance:  ${report['peak_balance']:,.2f} "
              f"(would become ${report['peak_balance_fixed']:,.2f})")
    print(f"{'='*55}\n")
    return report
