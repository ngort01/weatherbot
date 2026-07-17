"""Portfolio open-book snapshot and risk caps."""
from weatherbet import config
from weatherbet.storage import load_all_markets


def portfolio_snapshot(markets=None):
    """Aggregate open positions: counts and capital at risk (sum of costs)."""
    if markets is None:
        markets = load_all_markets()
    total = 0
    by_city = {}
    by_date = {}
    capital = 0.0
    for m in markets:
        pos = m.get("position") or {}
        if pos.get("status") != "open":
            continue
        total += 1
        city = m["city"]
        date = m["date"]
        by_city[city] = by_city.get(city, 0) + 1
        by_date[date] = by_date.get(date, 0) + 1
        capital += float(pos.get("cost") or 0.0)
    return {
        "total": total,
        "by_city": by_city,
        "by_date": by_date,
        "capital": capital,
    }

def risk_limit_reason(city_slug, date_str, cost, balance, book):
    """
    Return a human-readable skip reason if opening would breach portfolio caps,
    else None. `book` is a portfolio_snapshot dict (mutated by caller on open/close).
    """
    if book["total"] >= config.MAX_OPEN_POSITIONS:
        return f"max open positions ({config.MAX_OPEN_POSITIONS})"
    if book["by_city"].get(city_slug, 0) >= config.MAX_OPEN_PER_CITY:
        return f"max open per city ({config.MAX_OPEN_PER_CITY})"
    if book["by_date"].get(date_str, 0) >= config.MAX_OPEN_PER_DATE:
        return f"max open per date ({config.MAX_OPEN_PER_DATE})"
    equity = balance + book["capital"]
    if equity <= 0:
        return "no equity"
    if (book["capital"] + cost) / equity > config.MAX_CAPITAL_AT_RISK_PCT + 1e-12:
        return f"max capital at risk ({config.MAX_CAPITAL_AT_RISK_PCT:.0%})"
    return None

def book_register_open(book, city_slug, date_str, cost):
    book["total"] += 1
    book["by_city"][city_slug] = book["by_city"].get(city_slug, 0) + 1
    book["by_date"][date_str] = book["by_date"].get(date_str, 0) + 1
    book["capital"] += float(cost)

def book_register_close(book, city_slug, date_str, cost):
    book["total"] = max(0, book["total"] - 1)
    if city_slug in book["by_city"]:
        book["by_city"][city_slug] = max(0, book["by_city"][city_slug] - 1)
    if date_str in book["by_date"]:
        book["by_date"][date_str] = max(0, book["by_date"][date_str] - 1)
    book["capital"] = max(0.0, book["capital"] - float(cost))
