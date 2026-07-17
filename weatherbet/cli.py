"""Main loop and CLI entrypoints."""
import sys
import time
from datetime import datetime

import requests

from weatherbet import config
from weatherbet import calibration
from weatherbet.calibration import load_cal
from weatherbet.scan import scan_and_update, scan_preview
from weatherbet.monitor import monitor_positions
from weatherbet.state import load_state, save_state, print_reconcile, refresh_state_stats
from weatherbet.report import print_status, print_report


def run_loop():
    calibration._cal = load_cal()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — STARTING")
    print(f"{'='*55}")
    print(f"  Cities:     {len(config.LOCATIONS)}")
    print(f"  Balance:    ${config.BALANCE:,.0f} | Max bet: ${config.MAX_BET}")
    print(f"  Risk:       open≤{config.MAX_OPEN_POSITIONS} | "
          f"city≤{config.MAX_OPEN_PER_CITY} | date≤{config.MAX_OPEN_PER_DATE} | "
          f"capital≤{config.MAX_CAPITAL_AT_RISK_PCT:.0%}")
    print(
        f"  Scan:       {config.SCAN_INTERVAL//60} min | Monitor: {config.MONITOR_INTERVAL//60} min")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0)")
    print(f"  Data:       {config.DATA_DIR.resolve()}")
    print(f"  Ctrl+C to stop\n")

    last_full_scan = 0

    while True:
        now_ts = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Full scan once per hour
        if now_ts - last_full_scan >= config.SCAN_INTERVAL:
            print(f"[{now_str}] full scan...")
            try:
                new_pos, closed, resolved = scan_and_update()
                state = load_state()
                print(f"  balance: ${state['balance']:,.2f} | "
                      f"new: {new_pos} | closed: {closed} | resolved: {resolved}")
                last_full_scan = time.time()
            except KeyboardInterrupt:
                print(f"\n  Stopping — saving state...")
                save_state(load_state())
                print(f"  Done. Bye!")
                break
            except requests.exceptions.ConnectionError:
                print(f"  Connection lost — waiting 60 sec")
                time.sleep(60)
                continue
            except Exception as e:
                print(f"  Error: {e} — waiting 60 sec")
                time.sleep(60)
                continue
        else:
            # Quick stop monitoring
            print(f"[{now_str}] monitoring positions...")
            try:
                stopped = monitor_positions()
                if stopped:
                    state = load_state()
                    print(f"  balance: ${state['balance']:,.2f}")
            except Exception as e:
                print(f"  Monitor error: {e}")

        try:
            time.sleep(config.MONITOR_INTERVAL)
        except KeyboardInterrupt:
            print(f"\n  Stopping — saving state...")
            save_state(load_state())
            print(f"  Done. Bye!")
            break

def run_scan_once():
    """
    Dry-run scan: show markets found and positions that *would* open.
    Does not fill, resolve, or write state/market files.
    """
    calibration._cal = load_cal()

    print(f"\n{'='*55}")
    print(f"  WEATHERBET — SCAN PREVIEW (dry-run)")
    print(f"{'='*55}")
    print(f"  Cities:     {len(config.LOCATIONS)}")
    print(f"  Balance:    ${load_state()['balance']:,.2f} | Max bet: ${config.MAX_BET}")
    print(f"  Risk:       open≤{config.MAX_OPEN_POSITIONS} | "
          f"city≤{config.MAX_OPEN_PER_CITY} | date≤{config.MAX_OPEN_PER_DATE} | "
          f"capital≤{config.MAX_CAPITAL_AT_RISK_PCT:.0%}")
    print(f"  Sources:    ECMWF + HRRR(US) + METAR(D+0)")
    print(f"  Mode:       read-only — no paper fills, no disk writes")
    print(f"  Data:       {config.DATA_DIR.resolve()} (read for open book only)\n")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] preview scan...")
    try:
        found, would = scan_preview()
        print(f"  Done. Found {found} market(s); would open {would}.\n")
    except KeyboardInterrupt:
        print(f"\n  Interrupted — no changes written.")
        raise SystemExit(130)
    except requests.exceptions.ConnectionError:
        print(f"  Connection lost during scan.")
        raise SystemExit(1)
    except Exception as e:
        print(f"  Error: {e}")
        raise SystemExit(1)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "run"
    rest = argv[1:]
    if cmd == "run":
        run_loop()
    elif cmd == "scan":
        run_scan_once()
    elif cmd == "status":
        calibration._cal = load_cal()
        print_status()
    elif cmd == "report":
        calibration._cal = load_cal()
        print_report()
    elif cmd == "reconcile":
        apply = "--fix" in rest
        print_reconcile(apply=apply)
    elif cmd == "refresh":
        st = refresh_state_stats(write=True)
        print(f"\n  state.json portfolio stats refreshed from market files")
        print(f"  cash ${st['balance']:,.2f} | equity ${st.get('equity', 0):,.2f} | "
              f"realized {st.get('realized_pnl', 0):+.2f} | "
              f"open {st.get('open_count', 0)} closed {st.get('closed_count', 0)}\n")
    else:
        print("Usage: python weatherbet.py [run|scan|status|report|reconcile|refresh]")
        print("   or: python -m weatherbet [...]")
