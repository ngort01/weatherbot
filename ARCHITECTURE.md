# WeatherBet — Architecture

Single-file paper-trading bot for Polymarket **highest daily temperature** markets. It forecasts airport-station highs, matches the market bucket that contains that forecast, sizes a simulated YES buy with EV/Kelly filters, and manages the position until exit or resolution.

**No live orders.** The bot only reads Polymarket Gamma prices and debits/credits a simulated bankroll in `data/state.json`.

Entry point: `weatherbet.py`  
CLI: `python weatherbet.py [run|scan|status|report]`

- `run` — continuous loop (hourly full scan that **fills** paper trades + 10‑min monitor)
- `scan` — **dry-run** preview only: fetch forecasts/markets, print findings and would-be entries; no fills, no state/market writes
- `status` / `report` — read-only summaries

---

## Problem

Polymarket lists events like:

> Will the highest temperature in Chicago be between 72–73°F on July 17?

Each event is a partition of temperature **buckets** (exact degree, ranges, “or higher” / “or below”). Markets are often mispriced relative to a good forecast. The bot:

1. Forecasts the high at the **airport station** the market resolves on (not city center).
2. Finds the bucket that matches that forecast.
3. Compares model probability to market price.
4. If filters pass, paper-buys YES and manages the position.

Airport coordinates matter: NYC → KLGA, Dallas → KDAL, etc. City-center coords can be several degrees off and pick the wrong 1–2°F bucket.

---

## Big picture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         weatherbet.py (everything)                        │
│                                                                           │
│  CLI: run | status | report                                               │
│         │                                                                 │
│         ▼                                                                 │
│  ┌─────────────┐     every ~10 min      ┌──────────────────┐             │
│  │  run_loop() │ ─────────────────────► │ monitor_positions│             │
│  │             │     every ~60 min      │  stop / trail /  │             │
│  │             │ ─────────────────────► │  take-profit     │             │
│  └──────┬──────┘                        └────────┬─────────┘             │
│         │ full scan                              │                       │
│         ▼                                        │                       │
│  ┌─────────────────────────────────────────────┐ │                       │
│  │              scan_and_update()                │ │                       │
│  │  for each of 20 cities × next 4 days:        │ │                       │
│  │    forecasts → Polymarket event → filters    │ │                       │
│  │    open / stop / forecast-exit / resolve     │ │                       │
│  └──────┬───────────────┬───────────────┬───────┘ │                       │
└─────────┼───────────────┼───────────────┼─────────┼───────────────────────┘
          │               │               │         │
          ▼               ▼               ▼         ▼
   Open-Meteo      Aviation Weather   Gamma API   Visual Crossing
   ECMWF / HRRR        METAR          markets      actuals (VC_KEY)
          │               │               │         │
          └───────────────┴───────┬───────┴─────────┘
                                  ▼
                    data/state.json          data/markets/{city}_{date}.json
                    data/calibration.json    (forecasts, prices, position, PnL)
```

---

## Runtime loop (two cadences)

| Cadence    | Interval                         | Function              | What it does                                              |
|-----------|-----------------------------------|-----------------------|-----------------------------------------------------------|
| Full scan | `scan_interval` (default 3600s)   | `scan_and_update()`   | All cities, forecasts, open/close, resolution, calibration |
| Monitor   | hard-coded 600s                   | `monitor_positions()` | Open positions only: stop-loss, trailing stop, take-profit |

```text
time ──► [full scan]──[mon]──[mon]──[mon]──[mon]──[mon]──[full scan]──…
              │          │                              │
              │          └─ bid / stops / TP only       │
              └─ open new trades + heavy I/O ───────────┘
```

---

## External inputs

| Source                 | Auth        | Role |
|------------------------|-------------|------|
| Open-Meteo ECMWF       | None        | Daily max temp, all cities |
| Open-Meteo HRRR/GFS    | None        | US only, short horizon; preferred as “best” when present |
| METAR (Aviation Weather) | None      | Live station observation (stored on D+0; not primary trade signal) |
| Polymarket Gamma       | None        | Event by slug, bucket prices, resolve, bestAsk/bestBid at entry |
| Visual Crossing        | `VC_KEY` (.env) | Historical max for `actual_temp` → calibration |

“Best” forecast selection (`take_forecast_snapshot`):

- US city with HRRR available → HRRR
- Else ECMWF if available
- Else no tradeable forecast

---

## Data model

### Bankroll — `data/state.json`

```json
{
  "balance": 10000.0,
  "starting_balance": 10000.0,
  "total_trades": 0,
  "wins": 0,
  "losses": 0,
  "peak_balance": 10000.0
}
```

`wins` / `losses` count **held-to-resolution** settlements only, not stop/TP exits.

### Per market — `data/markets/{city}_{date}.json`

One file per city/date (not per bucket). Contents:

| Field | Purpose |
|-------|---------|
| `forecast_snapshots[]` | ECMWF / HRRR / METAR / `best` over time |
| `market_snapshots[]` | Top-bucket price history |
| `all_outcomes[]` | Every temp bucket + bid/ask/volume |
| `position` | `null` or open/closed paper trade |
| `status` | `open` \| `closed` \| `resolved` |
| `resolved_outcome` | `win` / `loss` / … |
| `actual_temp` | Station max after the day (Visual Crossing) |
| `pnl` | Realized PnL when held to resolution |
| `hold_to_resolution_pnl` | Counterfactual if exited early |

### Calibration — `data/calibration.json`

Keys `{city}_{source}` (e.g. `chicago_hrrr`):

- `sigma` — MAE of forecast vs actual
- `bias` — mean signed error
- `n` — sample count

Updated by `run_calibration` when enough markets have actuals (`calibration_min`, default 30). Used for **edge** buckets and intended for a fuller probability model later; middle-bucket trades today barely use it (see Math).

### Config — `config.json` + `.env`

Risk and trade knobs live in `config.json`. Secrets (`VC_KEY`) live in `.env`, not config.

---

## Decision pipeline (one city, one day)

```text
                    ┌──────────────────┐
                    │ forecasts (3 src)│
                    │ pick best:       │
                    │  US + HRRR → HRRR│
                    │  else ECMWF      │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ Gamma event slug │
                    │ highest-temp-in- │
                    │ {city}-on-{m-d-y}│
                    └────────┬─────────┘
                             ▼
              ┌──────────────────────────────┐
              │ Parse buckets from questions │
              │  "between 72-73°F" → (72,73) │
              │  "80°F" → (80,80)            │
              │  "90°F or higher" → (90,999) │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ Match: forecast ∈ bucket?    │  ← only ONE bucket considered
              └──────────────┬───────────────┘
                             │ no → skip
                             ▼ yes
              ┌──────────────────────────────┐
              │ Filters (all must pass)      │
              │  volume ≥ min_volume         │
              │  hours ∈ [min_hours, max]    │
              │  p = bucket_prob(...)        │
              │  EV(p, ask) ≥ min_ev         │
              │  kelly → size ≥ $0.50        │
              │  size ≤ max_bet              │
              │  re-fetch bestAsk/bestBid    │
              │  spread ≤ max_slippage       │
              │  ask < max_price             │
              │  portfolio risk caps         │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ PAPER BUY                    │
              │  balance -= cost             │
              │  position.status = "open"    │
              │  stop = entry × 0.80         │
              └──────────────────────────────┘
```

Design constraints:

1. **One position per city/date file.** After close, no re-entry on that market.
2. **Only the matched bucket** is evaluated — no shopping across tails for better EV.
3. **Paper only** — Gamma is read for prices; nothing is submitted to the CLOB.
4. Discovery skips new markets outside `[min_hours, max_hours]`.

---

## Math (as implemented)

### Probability — `bucket_prob`

| Bucket type | Probability |
|-------------|-------------|
| Middle / exact (`72–73` or `80`) | **Binary:** forecast in range → `p = 1.0`, else `0.0` |
| Edge (`or below` / `or higher`) | Normal CDF with σ from calibration (defaults: σ_F=2.0, σ_C=1.2) |

For a normal “mode” trade (forecast lands in a middle bin), **p is always 1.0**. EV and Kelly look extremely good and usually size to `max_bet`. This is characterized in tests and called out in `IMPROVEMENTS.md` §1 — not accidental, but not true continuous probability either.

### EV — `calc_ev`

```text
EV = p × (1/price − 1) − (1 − p)
```

With `p = 1` and ask = 0.32: `EV = 1/0.32 − 1 = +2.125` → clears `min_ev`.

### Kelly — `calc_kelly` / `bet_size`

```text
b  = 1/price − 1
f* = (p·b − (1−p)) / b
size = min(f* × kelly_fraction × balance, max_bet)
```

With `p = 1`, fractional Kelly saturates → almost always **`max_bet`** if cash allows.

### Portfolio risk (at open)

| Cap | Config key | Default |
|-----|------------|---------|
| Max open positions | `max_open_positions` | 20 |
| Max open per city | `max_open_per_city` | 2 |
| Max open per date | `max_open_per_date` | 6 |
| Capital at risk | `max_capital_at_risk_pct` | 0.2 (of equity = cash + open costs) |

Skips log as `[RISK] ...`.

---

## Position lifecycle

```text
OPEN
  │
  ├─ monitor every 10m ──► stop @ 80% of entry
  │                      ► trail to breakeven if mark ≥ entry × 1.20
  │                      ► take-profit by horizon:
  │                           ≥48h left → bid ≥ 0.75
  │                           24–48h    → bid ≥ 0.85
  │                           <24h      → hold (no TP)
  │
  ├─ full scan ──────────► same stop / trail
  │                      ► exit if forecast leaves bucket
  │                        by more than ~1–2° buffer
  │                        (reason: forecast_changed)
  │
  └─ resolution ─────────► Gamma: market closed + YES ~1 or ~0
                           held open → bankroll ± shares×(1−entry) or −cost
                                       wins++ / losses++
                           already exited → annotate win/loss only
                                           + hold_to_resolution_pnl
                           past calendar date → Visual Crossing actual_temp
                                       → calibration when n ≥ calibration_min
```

Exit reasons: `stop_loss`, `trailing_stop`, `take_profit`, `forecast_changed`, `resolved`.

---

## Module map (`weatherbet.py`)

| Section | Responsibility |
|---------|----------------|
| Config / `LOCATIONS` | Knobs + 20 airport stations |
| Math | `norm_cdf`, `bucket_prob`, `calc_ev`, `calc_kelly`, `bet_size` |
| Calibration | MAE/bias from resolved actuals |
| Portfolio risk | Open caps (`portfolio_snapshot`, `risk_limit_reason`) |
| Forecasts | ECMWF, HRRR, METAR, VC actuals |
| Polymarket | Event fetch, parse buckets, resolve |
| Storage | Per-market JSON + state |
| `scan_and_update` | Main trading brain |
| `monitor_positions` | Fast risk exits |
| `run_loop` / CLI | Orchestration |

---

## Dummy bet walkthrough

Concrete numbers with typical config (`max_bet` 20, `min_ev` 0.10, `max_price` 0.45, `max_slippage` 0.03, bankroll $10,000).

### Setup

| Field | Value |
|-------|--------|
| City | Chicago (`KORD`, °F) |
| Date | D+1 |
| Forecasts | ECMWF 73°F, HRRR **72°F** → **best = HRRR 72** |
| Hours left | 36 h (inside 2–72) |

### Buckets (simplified)

| Bucket | YES ask | Volume |
|--------|---------|--------|
| 70–71°F | $0.12 | 8,000 |
| **72–73°F** | **$0.32** | **12,000** |
| 74–75°F | $0.18 | 6,000 |
| 76°F or higher | $0.08 | 3,000 |

### Steps

1. **Match** — `in_bucket(72, 72, 73)` → true. Only this bucket is considered.
2. **Probability** — middle bucket → `bucket_prob` → **`p = 1.0`** (σ unused).
3. **Filters**

   | Check | Result |
   |-------|--------|
   | Volume 12k ≥ min_volume | pass |
   | Hours 36 ∈ [min_hours, max_hours] | pass |
   | EV = 1/0.32 − 1 = **+2.125** ≥ min_ev | pass |
   | Kelly → size → **$20** | pass |
   | Live ask $0.32, spread ≤ max_slippage, ask &lt; max_price | pass |
   | Portfolio caps | pass |

4. **Paper fill**

   ```text
   entry_price = 0.32
   cost        = 20.00
   shares      = 20 / 0.32 = 62.50
   stop_price  = 0.32 × 0.80 = 0.256
   balance     = 10000 − 20 = 9980
   ```

   Log style:

   ```text
   [BUY] Chicago D+1 2026-07-17 | 72.0-73.0F | $0.320 | EV +2.12 | $20.00 (HRRR)
   ```

5. **Possible endings**

   | Path | Example | Bankroll effect |
   |------|---------|-----------------|
   | Take-profit (36h → TP 0.85) | bid hits 0.85 | PnL = (0.85−0.32)×62.5 = **+$33.12** |
   | Stop | bid → 0.25 | PnL = (0.25−0.32)×62.5 = **−$4.38** |
   | Forecast flip | later high 78°F | sell at bid; `forecast_changed` |
   | Hold WIN | actual high 72–73 | exit 1.0; PnL = 62.5×(1−0.32) = **+$42.50**; wins++ |
   | Hold LOSS | actual high 70 | exit 0.0; PnL = **−$20**; losses++ |

   If TP fired and the bucket later won, the file still gets `resolved_outcome: win` and `hold_to_resolution_pnl`, but cash is not adjusted again.

6. **Learning** — After the calendar day, Visual Crossing stores e.g. `actual_temp: 73`. Residual vs last HRRR snapshot feeds `chicago_hrrr` calibration once `n ≥ calibration_min`.

---

## Mental model of the edge

```text
              Reality (resolution station high)
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
    Forecast μ      Bucket partition    Market prices
    (HRRR/ECMWF)    (1–2° bins)         (YES ¢)
         │               │               │
         └──────► match bin ◄────────────┘
                      │
                      ▼
            buy YES if cheap enough
            under binary p=1 model
```

Today’s strategy is essentially:

> My point-forecast bucket is treated as certain (`p=1`). If the book prices that bucket under `max_price` with enough volume and a tight spread, buy up to `max_bet` (subject to risk caps).

That is a **forecast-tracking / favorite-bucket** strategy with risk management — not a full probabilistic market-maker. Continuous `p` + calibrated σ would change which trades fire; see `IMPROVEMENTS.md` §1–2.

---

## Config knobs that matter most

| Key | Typical | Effect |
|-----|---------|--------|
| `min_ev` | 0.10 | Almost always true when p=1 and ask &lt; max_price |
| `max_price` | 0.45 | Never buy expensive favorites |
| `max_bet` | 20 | Effective size under binary p |
| `max_slippage` | 0.03 | Reject wide books |
| `min_hours` / `max_hours` | 2 / 72 | Horizon window |
| `kelly_fraction` | 0.25 | Fraction of full Kelly |
| Portfolio caps | 20 / 2 / 6 / 20% | Concentration limits |
| `calibration_min` | 30 | Samples before city/source σ updates |
| `scan_interval` | 3600 | Full scan period (seconds) |

---

## Related docs

| File | Role |
|------|------|
| `README.md` | Install, usage, API table |
| `IMPROVEMENTS.md` | Backlog (probability model, calibration, risk) |
| `TESTING_PLAN.md` | Characterization tests for current behavior |
| `tests/` | Unit tests pinning math, sizing, storage, risk |

---

## One-sentence summary

Hourly, scrape forecasts and Polymarket for 20 cities × 4 days; paper-buy YES on the single temperature bucket the best forecast lands in if liquidity/price/EV/risk pass; manage with stops, take-profit, and forecast flips; settle against Gamma; learn residual error from Visual Crossing.
