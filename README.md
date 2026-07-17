# 🌤 WeatherBet — Polymarket Weather Trading Bot

Automated weather market trading bot for Polymarket. Finds mispriced temperature outcomes using real forecast data from multiple sources across 20 cities worldwide.

No SDK. No black box. Pure Python.

---

## Versions

### Package `weatherbet/` — Full Bot (current)

Logic lives under `weatherbet/` (config, model, forecasts, scan, …). Run via `python weatherbet.py` or `python -m weatherbet`.

The bot features:
- **20 cities** across 4 continents (US, Europe, Asia, South America, Oceania)
- **3 forecast sources** — ECMWF (global), HRRR/GFS (US, hourly), METAR (real-time observations)
- **Expected Value** — skips trades where EV is below threshold (see `MODEL.md`)
- **Kelly Criterion** — fractional Kelly sizing, then `max_bet` (see `MODEL.md`)
- **Stop-loss + trailing stop** — 20% stop, moves to breakeven at +20%
- **Slippage filter** — skips markets with spread > $0.03
- **Self-calibration** — learns forecast accuracy per city over time
- **Full data storage** — every forecast snapshot, trade, and resolution saved to JSON

---

## How It Works

Polymarket runs markets like "Will the highest temperature in Chicago be between 46–47°F on March 7?" These markets are often mispriced — the forecast says 78% likely but the market is trading at 8 cents.

The bot:
1. Fetches forecasts from ECMWF and HRRR via Open-Meteo (free, no key required)
2. Gets real-time observations from METAR airport stations
3. Finds the matching temperature bucket on Polymarket
4. Calculates Expected Value — only enters if EV ≥ `min_ev` (`MODEL.md`)
5. Sizes the position with fractional Kelly, capped by `max_bet`
6. Monitors stops every 10 minutes, full scan every hour
7. Auto-resolves markets by querying Polymarket API directly

---

## Why Airport Coordinates Matter

Most bots use city center coordinates. That's wrong.

Every Polymarket weather market resolves on a specific airport station. NYC resolves on LaGuardia (KLGA), Dallas on Love Field (KDAL) — not DFW. The difference between city center and airport can be 3–8°F. On markets with 1–2°F buckets, that's the difference between the right trade and a guaranteed loss.

| City | Station | Airport |
|------|---------|---------|
| NYC | KLGA | LaGuardia |
| Chicago | KORD | O'Hare |
| Miami | KMIA | Miami Intl |
| Dallas | KDAL | Love Field |
| Seattle | KSEA | Sea-Tac |
| Atlanta | KATL | Hartsfield |
| London | EGLC | London City |
| Tokyo | RJTT | Haneda |
| ... | ... | ... |

---

## Installation
```bash
git clone https://github.com/alteregoeth-ai/weatherbot
cd weatherbot
pip install requests
```

Create `config.json` in the project folder:
```json
{
  "balance": 10000.0,
  "max_bet": 20.0,
  "min_ev": 0.05,
  "max_price": 0.45,
  "min_volume": 2000,
  "min_hours": 2.0,
  "max_hours": 72.0,
  "kelly_fraction": 0.25,
  "max_slippage": 0.03,
  "scan_interval": 3600,
  "calibration_min": 30,
  "vc_key": "YOUR_VISUAL_CROSSING_KEY"
}
```

Get a free Visual Crossing API key at visualcrossing.com — used to fetch actual temperatures after market resolution.

---

## Usage
```bash
python weatherbet.py           # start the bot — scans every hour, monitors every 10 min
python weatherbet.py scan      # dry-run preview: markets + would-be trades (no fills)
python weatherbet.py status    # balance and open positions
python weatherbet.py report    # full breakdown of all resolved markets
python weatherbet.py reconcile # audit state.json cash vs market files
python weatherbet.py reconcile --fix  # rewrite balance if they drift
python weatherbet.py refresh   # rebuild portfolio KPIs in state.json from markets
```

---

## Tests

Characterization tests pin **current** bot behavior (including binary middle-bucket probabilities). See `TESTING_PLAN.md`.

```bash
pip install -r requirements-dev.txt
pytest
```

---

## Docs

| Doc | For |
|-----|-----|
| [`AGENTS.md`](AGENTS.md) | AI agents / contributors — invariants, traps, how to change code safely |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How the bot works, data model, dummy bet walkthrough |
| [`IMPROVEMENTS.md`](IMPROVEMENTS.md) | Backlog and known design issues |
| [`TESTING_PLAN.md`](TESTING_PLAN.md) | Characterization test philosophy and coverage plan |

---

## Data Storage

All data is saved to `data/markets/` — one JSON file per market. Each file contains:
- Hourly forecast snapshots (ECMWF, HRRR, METAR)
- Market price history
- Position details (entry, stop, PnL)
- Final resolution outcome

This data is used for self-calibration — the bot learns forecast accuracy per city over time and adjusts position sizing accordingly.

---

## APIs Used

| API | Auth | Purpose |
|-----|------|---------|
| Open-Meteo | None | ECMWF + HRRR forecasts |
| Aviation Weather (METAR) | None | Real-time station observations |
| Polymarket Gamma | None | Market data |
| Visual Crossing | Free key | Historical temps for resolution |

---

## Disclaimer

This is not financial advice. Prediction markets carry real risk. Run the simulation thoroughly before committing real capital.
