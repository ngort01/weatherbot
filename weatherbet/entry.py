"""Entry signal evaluation (filters, EV, live book, risk)."""
import requests

from weatherbet import config
from weatherbet.model import (
    bucket_prob, calc_ev, calc_kelly, bet_size, compute_stop_price,
)
from weatherbet.calibration import get_sigma, get_bias
from weatherbet.forecasts import forecast_panel
from weatherbet.polymarket import in_bucket
from weatherbet.risk import risk_limit_reason


def _liquidity_usd(mdata):
    """Parse Gamma market liquidity if present; else None."""
    if not mdata:
        return None
    raw = mdata.get("liquidityNum", mdata.get("liquidity"))
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def consider_entry(
    city_slug,
    date_str,
    outcomes,
    forecast_temp,
    best_source,
    hours,
    balance,
    book,
    *,
    opened_at=None,
    fetch_live_book=True,
    forecast_snap=None,
):
    """
    Evaluate opening YES on the single forecast-matched bucket.

    Returns (signal_or_None, skip_reason_or_None).
    Does not mutate book, balance, or market files.
    When signal is returned, skip_reason is None and the caller may open (or preview).
    Optional forecast_snap attaches forecast_panel (source temps + spread) for observability.
    """
    if forecast_temp is None:
        return None, "no forecast"
    if hours < config.MIN_HOURS:
        return None, f"hours {hours:.1f} < min {config.MIN_HOURS}"
    if hours > config.MAX_HOURS:
        return None, f"hours {hours:.1f} > max {config.MAX_HOURS}"

    matched = None
    for o in outcomes:
        t_low, t_high = o["range"]
        if in_bucket(forecast_temp, t_low, t_high):
            matched = o
            break
    if not matched:
        return None, "no matching bucket"

    t_low, t_high = matched["range"]
    volume = matched["volume"]
    # outcomePrices are YES/NO — only useful as a rough mid until live book
    yes_mid = matched.get(
        "yes_price", matched.get("bid", matched.get("price", 0.5))
    )

    if volume < config.MIN_VOLUME:
        return None, f"volume {volume:.0f} < min {config.MIN_VOLUME}"

    src = best_source or "ecmwf"
    sigma = get_sigma(city_slug, src)
    bias = get_bias(city_slug, src)
    p = bucket_prob(forecast_temp, t_low, t_high, sigma, bias)

    # Provisional size from bankroll/kelly; final EV/shares use entry price
    # (live bestAsk when available — never NO price from outcomePrices).
    provisional_price = yes_mid if 0 < yes_mid < 1 else 0.5
    kelly = calc_kelly(p, provisional_price)
    size = bet_size(kelly, balance)
    if size < 0.50:
        return None, f"size ${size:.2f} < $0.50"

    signal = {
        "market_id":     matched["market_id"],
        "question":      matched["question"],
        "bucket_low":    t_low,
        "bucket_high":   t_high,
        "entry_price":   provisional_price,
        "bid_at_entry":  provisional_price,
        "spread":        None,
        "shares":        round(size / provisional_price, 2),
        "cost":          size,
        "p":             round(p, 4),
        "ev":            round(calc_ev(p, provisional_price), 4),
        "kelly":         round(kelly, 4),
        "forecast_temp": forecast_temp,
        "forecast_src":  best_source,
        "sigma":         sigma,
        "bias":          bias,
        "opened_at":     opened_at,
        "status":        "open",
        "pnl":           None,
        "exit_price":    None,
        "close_reason":  None,
        "closed_at":     None,
        "stop_price":    compute_stop_price(provisional_price),
        "book_source":   "yes_mid",  # upgraded to "clob" after live fetch
        "liquidity_usd": None,
    }
    panel = forecast_panel(forecast_snap) if forecast_snap is not None else None
    if panel is not None:
        signal["forecast_panel"] = panel

    if fetch_live_book:
        try:
            r = requests.get(
                f"https://gamma-api.polymarket.com/markets/{signal['market_id']}",
                timeout=(3, 5),
            )
            mdata = r.json()
            real_ask = float(mdata.get("bestAsk", signal["entry_price"]))
            real_bid = float(mdata.get("bestBid", signal["bid_at_entry"]))
            real_spread = round(real_ask - real_bid, 4)
            if real_ask <= 0:
                return None, "invalid live ask"
            if real_ask < config.MIN_PRICE:
                return None, (
                    f"ask ${real_ask:.3f} < min_price {config.MIN_PRICE}"
                )
            if real_ask >= config.MAX_PRICE:
                return None, (
                    f"real ask ${real_ask:.3f} >= max_price {config.MAX_PRICE}"
                )
            if real_spread > config.MAX_SLIPPAGE:
                return None, (
                    f"real ask ${real_ask:.3f} spread ${real_spread:.3f}"
                    f" > max_slippage {config.MAX_SLIPPAGE}"
                )
            liq = _liquidity_usd(mdata)
            signal["liquidity_usd"] = liq
            if config.MIN_ASK_DEPTH_USD > 0 and liq is not None:
                need = max(float(signal["cost"]), config.MIN_ASK_DEPTH_USD)
                if liq < need:
                    return None, (
                        f"liquidity ${liq:.0f} < min depth "
                        f"${need:.0f}"
                    )
            signal["entry_price"] = real_ask
            signal["bid_at_entry"] = real_bid
            signal["spread"] = real_spread
            signal["shares"] = round(signal["cost"] / real_ask, 2)
            signal["ev"] = round(calc_ev(signal["p"], real_ask), 4)
            signal["kelly"] = round(calc_kelly(signal["p"], real_ask), 4)
            signal["stop_price"] = compute_stop_price(real_ask)
            signal["book_source"] = "clob"
        except Exception as e:
            # No trustworthy ask — do not pretend NO-price is a buy price
            return None, f"live book fetch failed: {e}"

    # Require a CLOB ask when live book was requested (normal path)
    if fetch_live_book and signal.get("book_source") != "clob":
        return None, "no live CLOB quote"

    entry = signal["entry_price"]
    if entry <= 0 or entry >= 1:
        return None, "invalid entry price"
    if entry < config.MIN_PRICE:
        return None, (
            f"ask ${entry:.3f} < min_price {config.MIN_PRICE}"
        )
    if entry >= config.MAX_PRICE:
        return None, (
            f"ask ${entry:.3f} >= max_price {config.MAX_PRICE}"
        )
    spread = signal.get("spread")
    if spread is not None and spread > config.MAX_SLIPPAGE:
        return None, (
            f"spread ${spread:.3f} > max_slippage {config.MAX_SLIPPAGE}"
        )
    if signal["ev"] < config.MIN_EV:
        return None, f"EV {signal['ev']:+.4f} < min {config.MIN_EV}"

    signal["stop_price"] = compute_stop_price(entry)

    risk_skip = risk_limit_reason(
        city_slug, date_str, signal["cost"], balance, book
    )
    if risk_skip:
        return None, f"risk: {risk_skip}"

    return signal, None

def _fmt_bucket(t_low, t_high, unit_sym):
    if t_low == -999:
        return f"≤{t_high}{unit_sym}"
    if t_high == 999:
        return f"≥{t_low}{unit_sym}"
    if t_low == t_high:
        return f"{t_low}{unit_sym}"
    return f"{t_low}-{t_high}{unit_sym}"

def _fmt_temp(val, unit_sym):
    if val is None:
        return "—"
    return f"{val}{unit_sym}"
