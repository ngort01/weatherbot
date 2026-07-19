# WeatherBet — Polymarket highest-temp paper bot

Paper-trading bot for Polymarket **highest daily temperature** markets.

Finds the bucket the forecast lands in, prices residual Gaussian mass against the YES ask, and either takes the edge or sits the fuck down. No SDK. No "AI agentic trading platform." Pure Python, `requests`, and a JSON bankroll you can actually grep.

**Does not place live orders.** Paper only until you explicitly go live (and if you do: official Polymarket `py-sdk`, env secrets, kill switch — see `IMPROVEMENTS.md` §8–9). YOLO on mainnet before resolved sample size is how you get heemed by a 1° station miss.

---

## What it actually does

Logic lives in `weatherbet/`. Run via `python weatherbet.py` or `python -m weatherbet`.

- **20 cities** — airports, not downtown vibes (US / EU / Asia / LatAm / Oceania)
- **Forecasts** — ECMWF (global), HRRR/GFS (US), METAR on the station
- **Partition `p`** — residual Gaussian mass on the **matched** bucket only (`MODEL.md`). Binary `p=1` on match is dead. Good riddance.
- **EV gate** — skip unless `EV ≥ min_ev`
- **Fractional Kelly** then hard `max_bet` — Kelly is not a personality trait
- **Stops** — stop = entry − max(`stop_loss_pct` × entry, `min_stop_width`); trail to breakeven at +20%
- **Forecast residual-edge exit** — mode left the bucket? Sell only when `p − bid ≤ forecast_exit_min_edge`, confirmed over `forecast_exit_confirm_scans` consecutive scans (force confirm=1 when `hours_left < forecast_exit_fast_hours`). Panic-selling residual edge is paper hands with a weather API.
- **Book filters** — `min_price`, spread/`max_slippage`, optional Gamma depth, portfolio caps (total / city / date / capital %)
- **Calibration** — learns σ/bias per city×source from actuals; uncalibrated σ=2 systematically hates 30–45¢ favorites (Trap B — not a free bugfix)
- **Full tape** — every snap, fill, exit, resolution under `data/`

---

## How it works (short)

Polymarket runs shit like: *Will the highest temperature in Chicago be between 72–73°F on July 17?*

Often mispriced vs a good airport forecast. Often correctly priced and you're just cope-reading the book. The bot doesn't care about your narrative — it cares about residual mass vs ask.

1. Forecast high at the **resolution airport** (Open-Meteo ECMWF/HRRR + METAR)
2. Match the **one** temp bucket that contains that forecast (no shopping tails for juicier EV)
3. `bucket_prob` → EV vs ask → Kelly size → risk caps
4. Paper-buy YES if everything clears
5. Monitor stops every `monitor_interval` (~10m); full scan every `scan_interval` (~1h)
6. Forecast drift: recompute residual edge before early exit
7. Resolve on Gamma; learn residuals from Visual Crossing actuals

Math pin: **`MODEL.md`**. Dummy bet walkthrough: **`ARCHITECTURE.md`**. Traps: **`IMPROVEMENTS.md`**.

---

## Why airport coordinates matter (don't be regarded)

City-center coords are how you lose money with confidence.

Every Polymarket weather market resolves on a **specific airport station**. NYC → KLGA (LaGuardia). Dallas → KDAL (Love Field), **not** DFW. Downtown vs airport can be 3–8°F. On 1–2° buckets that's not "noise" — that's buying the wrong contract and then writing a blog post about volatility.

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
| … | … | full map in `config` / `LOCATIONS` |

---

## Install

```bash
git clone https://github.com/alteregoeth-ai/weatherbot
cd weatherbot
pip install -r requirements-dev.txt   # or: pip install requests python-dotenv
```

Strategy knobs live in committed `config.json`. Edit them. **Do not put secrets here.**
(Comments below are README-only — real `config.json` is strict JSON, no `//`.)

```jsonc
{
  // Starting paper bankroll seed. Runtime cash lives in data/state.json — this is not your live wallet, regard.
  "balance": 10000.0,

  // Hard $ cap per fill. Kelly can propose less; it cannot propose more. Leash, not personality.
  "max_bet": 20.0,

  // Minimum EV to open. Uncalibrated σ=2 → mode mass ~20% → 30–45¢ favorites often fail this (Trap B). Not a free "be more aggressive" dial.
  "min_ev": 0.05,

  // Never buy YES at/above this. Expensive favorites are where hopium pays the vig.
  "max_price": 0.45,

  // Never buy YES below this. Penny stubs (Tel‑Aviv-class) are stop food, not alpha.
  "min_price": 0.08,

  // Min matched-bucket volume. Illiquid trash still has a price — doesn't mean you can exit.
  "min_volume": 500,

  // Don't enter if resolution is closer than this (hours). Last-minute lottery tickets need a thesis, not a cron.
  "min_hours": 2.0,

  // Don't enter if resolution is farther than this. D+3 weather is fan fiction with a temperature label.
  "max_hours": 72.0,

  // Fraction of full Kelly. 0.25 = quarter Kelly. Full Kelly on correlated heat waves is how you get heemed by one airmass.
  "kelly_fraction": 0.25,

  // Full scan period (seconds): forecasts + Gamma + entry/exit + resolve. ~1h default.
  "scan_interval": 3600,

  // Between scans: stop / trail / TP only (seconds). ~10m default. Price death doesn't wait for the hourly meeting.
  "monitor_interval": 600,

  // Min residual samples before city×source σ/bias leaves defaults. Empty cal is a wait, not a bug — don't fake n.
  "calibration_min": 20,

  // Max ask−bid on live CLOB. Wide book = you're the exit liquidity for someone else's bag.
  "max_slippage": 0.03,

  // When Gamma reports liquidity USD, require ≥ max(cost, this). 0 = off. Missing liquidity does not skip.
  "min_ask_depth_usd": 25.0,

  // Stop distance as fraction of entry. Combined with min_stop_width: stop = entry − max(entry×pct, width).
  "stop_loss_pct": 0.20,

  // Floor on stop distance in price units. Cheap entries still need room or every tick is a stop-out.
  "min_stop_width": 0.05,

  // Forecast left bucket+buffer: sell only if residual edge p−bid ≤ this. 0 = hold while model still > salvage (Paris-17). Paper hands use a weather API.
  "forecast_exit_min_edge": 0.0,

  // Consecutive edge-gone scans before forecast_changed. 1 = off (residual edge only). ≥2 = multi-scan wait — replay didn't clearly print; leave at 1 unless you're experimenting.
  "forecast_exit_confirm_scans": 1,

  // If hours_left < this, force confirm=1 even when confirm_scans ≥ 2. Near resolve, waiting another hourly scan is how dust eats you.
  "forecast_exit_fast_hours": 6.0,

  // Max simultaneous open positions. Correlation doesn't care that they're "different cities."
  "max_open_positions": 20,

  // Max opens per city slug. Don't ladder the same station into oblivion.
  "max_open_per_city": 2,

  // Max opens per calendar date. One cold front, six jerseys — still one bet.
  "max_open_per_date": 6,

  // Max sum(open costs) / equity. Equity ≈ cash + open cost basis (not live MTM fantasy).
  "max_capital_at_risk_pct": 0.2
}
```

Secrets → `.env` only:

```bash
cp .env.example .env
# VC_KEY=... from visualcrossing.com (free tier is fine)
```

Visual Crossing is for **actuals after resolution** so calibration isn't vibes. Commit a real key and you're the risk event.

---

## Usage

```bash
python weatherbet.py              # main loop: hourly scan (fills) + 10m monitor
python weatherbet.py scan         # dry-run: markets + would-be trades, no fills/writes
python weatherbet.py status       # cash, opens, model-vs-market tape
python weatherbet.py report       # resolved breakdown + cal summary
python weatherbet.py reconcile    # audit state.json cash vs market files
python weatherbet.py reconcile --fix  # rewrite balance if they drift (markets win)
python weatherbet.py refresh      # rebuild portfolio KPIs from market files
```

Run from **repo root** so `config.json` loads from cwd. Point experimental runs at isolated `data/` paths if you value your paper history.

---

## Tests

Characterization suite pins **what the code does now**, including partition `p` and residual-edge exits — not the fantasy bot in your head.

```bash
pip install -r requirements-dev.txt
pytest
```

See `TESTING_PLAN.md`. Offline only — mock network or you're testing your wifi.

---

## Docs (read these before "fixing" the math)

| Doc | For |
|-----|-----|
| [`AGENTS.md`](AGENTS.md) | Invariants, traps, where to edit without nuking the strategy |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Loop, data model, dummy bet, exit matrix |
| [`MODEL.md`](MODEL.md) | Probability / EV / Kelly / residual-edge exit — the pin |
| [`IMPROVEMENTS.md`](IMPROVEMENTS.md) | Brutal backlog + design traps (Trap A/B live here) |
| [`TESTING_PLAN.md`](TESTING_PLAN.md) | What tests lock and why |

If you're about to "just use continuous Φ on raw `[t_low, t_high]`" for exact bins: **stop.** That's Trap A. `p=0` forever. Read `IMPROVEMENTS.md` §1.

---

## Data

Everything under `data/` (gitignored runtime state — don't commit your paper trauma unless you mean it):

| Path | What |
|------|------|
| `data/state.json` | Paper bankroll + rebuilt KPIs |
| `data/markets/{city}_{date}.json` | One file per city/date: snaps, book, position, resolve |
| `data/calibration.json` | Per `{city}_{source}` σ / bias / n |

Market files are **source of truth** for trades. `state.json` is cash + summary — if they disagree, markets win. Early exit does **not** get a second bankroll credit at resolution; that's how you invent tendies.

---

## APIs

| API | Auth | Purpose |
|-----|------|---------|
| Open-Meteo | None | ECMWF + HRRR forecasts |
| Aviation Weather (METAR) | None | Live station obs |
| Polymarket Gamma | None | Events, prices, resolve |
| Visual Crossing | `VC_KEY` | Historical max for calibration |

---

## Don't

- Live trade before you have a resolved track record that isn't cope
- Trust unrealized PnL on open weather marks as "alpha"
- Downtown coords because "city center is more accurate"
- Binary certainty because the forecast matched the label
- Commit `.env`
- Pretend Kelly is risk management while you max-bet every city on the same cold front

---

## Disclaimer (read it, regard)

This is **paper**. Default path never touches a wallet. If you wire live trading yourself and ape size before you have a resolved track record, that is not "the bot failed" — that is you.

Prediction markets still rekt people who confuse vibes for edge. Weather contracts rekt people who use downtown coords, ignore resolution stations, and treat a matched forecast as p=1. Liquidity is thin, spreads are real, and a 1° station miss can zero a "sure thing" favorite.

Nothing here is a promise of tendies. Math can be right and you still lose. Math can be wrong and you print for a week and learn nothing. Run the sim until the tape is boring. If you go live, use official tooling, env secrets, a kill switch, and size like you actually read `IMPROVEMENTS.md` §8–9.

You are responsible for your own bags. Don't @ us when Gamma settles against your hopium.
