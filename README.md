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
- **Partition probability** — Gaussian residual mass on the forecast-matched bucket (see `MODEL.md`)
- **Expected Value** — skips trades where EV is below `min_ev` (see `MODEL.md`)
- **Kelly Criterion** — fractional Kelly sizing, then `max_bet` (see `MODEL.md`)
- **Stop-loss + trailing stop** — stop = entry − max(`stop_loss_pct` × entry, `min_stop_width`); trail to breakeven at +20%
- **Forecast residual-edge exit** — if forecast leaves the bucket, sell only when model `p` no longer exceeds salvage bid (`forecast_exit_min_edge`)
- **Min price / depth** — skip asks below `min_price` and thin Gamma liquidity when reported
- **Portfolio caps** — max open positions / per city / per date / capital at risk
- **Slippage filter** — skips markets with spread > `max_slippage`
- **Self-calibration** — learns forecast accuracy per city over time
- **Full data storage** — every forecast snapshot, trade, and resolution saved to JSON

---

## How It Works

Polymarket runs markets like "Will the highest temperature in Chicago be between 46–47°F on March 7?" These markets are often mispriced — the forecast says 78% likely but the market is trading at 8 cents.

The bot:
1. Fetches forecasts from ECMWF and HRRR via Open-Meteo (free, no key required)
2. Gets real-time observations from METAR airport stations
3. Finds the matching temperature bucket on Polymarket (matched-bucket only)
4. Calculates partition `p` and EV — only enters if EV ≥ `min_ev` (`MODEL.md`)
5. Sizes the position with fractional Kelly, capped by `max_bet`
6. Monitors stops every `monitor_interval` (default 10 min); full scan every `scan_interval` (default 1h)
7. On forecast drift: recomputes residual edge vs bid before early exit
8. Auto-resolves markets by querying Polymarket API directly

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
pip install -r requirements-dev.txt   # or: pip install requests python-dotenv
```

Strategy knobs ship in committed `config.json` (edit in place; do not put secrets here):

```json
{
  "balance": 10000.0,
  "max_bet": 20.0,
  "min_ev": 0.05,
  "max_price": 0.45,
  "min_price": 0.08,
  "min_volume": 500,
  "min_hours": 2.0,
  "max_hours": 72.0,
  "kelly_fraction": 0.25,
  "scan_interval": 3600,
  "monitor_interval": 600,
  "calibration_min": 20,
  "max_slippage": 0.03,
  "min_ask_depth_usd": 25.0,
  "stop_loss_pct": 0.20,
  "min_stop_width": 0.05,
  "forecast_exit_min_edge": 0.0,
  "max_open_positions": 20,
  "max_open_per_city": 2,
  "max_open_per_date": 6,
  "max_capital_at_risk_pct": 0.2
}
```

Secrets go in `.env` (see `.env.example`):

```bash
cp .env.example .env
# edit: VC_KEY=...
```

Get a free Visual Crossing API key at visualcrossing.com — used to fetch actual temperatures after market resolution (`VC_KEY` only; never commit real keys).

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

Characterization tests pin **current** bot behavior (partition residual probabilities). See `TESTING_PLAN.md` and `MODEL.md`.

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
| [`MODEL.md`](MODEL.md) | Probability, EV, Kelly, residual-edge forecast exit |
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
