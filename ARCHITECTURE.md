# WeatherBet — Architecture

Paper-trading bot for Polymarket **highest daily temperature** markets. It forecasts airport-station highs, matches the market bucket that contains that forecast, sizes a simulated YES buy with EV/Kelly filters, and manages the position until exit or resolution.

Logic lives in the **`weatherbet/` package** (plain modules, no trading SDK). Root `weatherbet.py` is a thin launcher.

**No live orders.** The bot only reads Polymarket Gamma prices and debits/credits a simulated bankroll in `data/state.json`.

Entry: `python weatherbet.py …` or `python -m weatherbet …`  
CLI: `run | scan | status | report | reconcile | refresh`

- `run` — continuous loop (hourly full scan that **fills** paper trades + 10‑min monitor)
- `scan` — **dry-run** preview only: fetch forecasts/markets, print findings and would-be entries; no fills, no state/market writes
- `status` / `report` — read-only summaries (`status` also refreshes portfolio KPIs in `state.json`)
- `reconcile [--fix]` — audit (or repair) cash vs market files
- `refresh` — rebuild portfolio summary fields in `state.json` from markets

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
┌──────────────────────────────── weatherbet/ ──────────────────────────────┐
│  cli.py  (run_loop, scan, status, report, reconcile, refresh)               │
│         │                                                                   │
│         ▼                                                                   │
│  ┌─────────────┐     every ~10 min      ┌──────────────────┐               │
│  │  run_loop   │ ─────────────────────► │ monitor.py       │               │
│  │             │     every ~60 min      │  stop / trail /  │               │
│  │             │ ─────────────────────► │  take-profit     │               │
│  └──────┬──────┘                        └────────┬─────────┘               │
│         │ full scan                              │                         │
│         ▼                                        │                         │
│  ┌─────────────────────────────────────────────┐ │                         │
│  │  scan.py — scan_and_update()                │ │                         │
│  │  for each of 20 cities × next 4 days:       │ │                         │
│  │    forecasts → Polymarket event → filters   │ │                         │
│  │    open / stop / forecast-exit / resolve    │ │                         │
│  └──────┬───────────────┬───────────────┬──────┘ │                         │
└─────────┼───────────────┼───────────────┼────────┼─────────────────────────┘
          │               │               │        │
          ▼               ▼               ▼        ▼
   Open-Meteo      Aviation Weather   Gamma API  Visual Crossing
   ECMWF / HRRR        METAR          markets     actuals (VC_KEY)
          │               │               │        │
          └───────────────┴───────┬───────┴────────┘
                                  ▼
                    data/state.json          data/markets/{city}_{date}.json
                    data/calibration.json    (forecasts, prices, position, PnL)
```

---

## Runtime loop (two cadences)

| Cadence    | Interval                         | Function              | What it does                                              |
|-----------|-----------------------------------|-----------------------|-----------------------------------------------------------|
| Full scan | `scan_interval` (default 3600s)   | `scan_and_update()`   | All cities, forecasts, open/close, resolution, calibration |
| Monitor   | `monitor_interval` (default 600s) | `monitor_positions()` | Open positions only: stop-loss, trailing stop, take-profit |

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

Cash ledger fields are updated on open/close/settle. Portfolio summary fields are **rebuilt from `data/markets/*.json`** on each full scan, monitor close, `status`, `refresh`, or `reconcile --fix` (market files stay source of truth for trades).

```json
{
  "balance": 10000.0,
  "starting_balance": 10000.0,
  "peak_balance": 10000.0,
  "total_trades": 0,
  "wins": 0,
  "losses": 0,
  "updated_at": null,
  "realized_pnl": 0.0,
  "closed_count": 0,
  "open_count": 0,
  "open_capital": 0.0,
  "equity": 10000.0,
  "return_pct": 0.0,
  "drawdown_pct": 0.0,
  "exits": {},
  "bucket_outcomes": {"win": 0, "loss": 0, "pending": 0},
  "hold_vs_exit": {
    "annotated": 0,
    "exit_pnl_sum": 0.0,
    "hold_pnl_sum": 0.0,
    "hold_minus_exit": 0.0
  },
  "actuals_count": 0
}
```

| Field | Meaning |
|-------|---------|
| `balance` / `peak_balance` | Paper cash and high-water mark |
| `wins` / `losses` | **Held-to-resolution** only (not stop/TP/forecast exits) |
| `total_trades` | Open + closed positions in market files |
| `realized_pnl` | Sum of closed `position.pnl` |
| `equity` | Cash + open cost (open marked at cost) |
| `return_pct` | Equity vs `starting_balance` |
| `drawdown_pct` | Cash vs `peak_balance` |
| `exits` | Per `close_reason`: `{n, pnl}` |
| `bucket_outcomes` | Polymarket bucket win/loss/pending (includes early exits once annotated) |
| `hold_vs_exit` | Counterfactual sum: hold-to-resolution PnL vs early-exit PnL |
| `actuals_count` | Markets with `actual_temp` filled |

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

Updated by `run_calibration` when enough markets have actuals (`calibration_min`, default 20). Used for **edge** buckets and intended for a fuller probability model later; middle-bucket trades today barely use it (see Math).

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
              │  ask ≥ min_price             │
              │  spread ≤ max_slippage       │
              │  ask < max_price             │
              │  liquidity ≥ min_ask_depth   │
              │  portfolio risk caps         │
              └──────────────┬───────────────┘
                             ▼
              ┌──────────────────────────────┐
              │ PAPER BUY                    │
              │  balance -= cost             │
              │  position.status = "open"    │
              │  stop = entry − max(         │
              │    entry×stop_loss_pct,      │
              │    min_stop_width)           │
              └──────────────────────────────┘
```

Design constraints:

1. **One position per city/date file.** After close, no re-entry on that market.
2. **Only the matched bucket** is evaluated — no shopping across tails for better EV.
3. **Paper only** — Gamma is read for prices; nothing is submitted to the CLOB.
4. Discovery skips new markets outside `[min_hours, max_hours]`.

---

## Math (as implemented)

Full formulas, worked examples, and partition-`p` implications: **`MODEL.md`**.

Short summary:

| Step | Behavior today |
|------|----------------|
| `bucket_prob` | Gaussian mass over `resolution_bin` (all buckets); μ = forecast − bias |
| `calc_ev` | YES EV at ask; positive only when model `p` beats price enough for `min_ev` |
| `calc_kelly` / `bet_size` | Fractional Kelly (`kelly_fraction`, default 0.25) then **`max_bet`** |

Matched-bucket only; size follows real edge (often below `max_bet` when `p` is modest). Design notes: `IMPROVEMENTS.md` §1.

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
  ├─ monitor every 10m ──► stop @ entry − max(pct, min_width)
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

## Module map (`weatherbet/`)

| Module | Responsibility |
|--------|----------------|
| `config.py` | `config.json` / `.env`, paths, `LOCATIONS`, strategy knobs |
| `model.py` | `norm_cdf`, `resolution_bin`, `bucket_prob`, `event_bucket_probs`, `calc_ev`, `calc_kelly`, `bet_size` — see **`MODEL.md`** |
| `calibration.py` | MAE/bias from resolved actuals (`_cal` cache) |
| `risk.py` | Open caps (`portfolio_snapshot`, `risk_limit_reason`) |
| `forecasts.py` | ECMWF, HRRR, METAR, VC actuals |
| `polymarket.py` | Event fetch, parse buckets, resolve |
| `storage.py` | Per-market JSON under `data/markets/` |
| `state.py` | `state.json`, reconcile, portfolio KPIs |
| `entry.py` | `consider_entry` filters + paper signal |
| `scan.py` | `scan_and_update` / `scan_preview` |
| `monitor.py` | Fast risk exits (stop / trail / TP) |
| `report.py` | `status` / `report` printing |
| `cli.py` | `run_loop` + CLI dispatch |
| `weatherbet.py` (root) | Thin launcher only |

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
2. **Probability** — matched bucket → `bucket_prob` → continuous partition mass under calibrated σ/bias (see `MODEL.md`).
3. **Filters**

   | Check | Result |
   |-------|--------|
   | Volume 12k ≥ min_volume | pass |
   | Hours 36 ∈ [min_hours, max_hours] | pass |
   | EV ≥ min_ev (partition `p` vs ask 0.32; needs tight enough σ) | pass if calibrated |
   | Kelly → size → up to **$20** (`max_bet`) | pass |
   | Live ask $0.32 (≥ min_price), spread ≤ max_slippage, ask &lt; max_price | pass |
   | Liquidity ≥ min_ask_depth_usd when reported | pass |
   | Portfolio caps | pass |

4. **Paper fill**

   ```text
   entry_price = 0.32
   cost        = 20.00
   shares      = 20 / 0.32 = 62.50
   stop_price  = 0.32 − max(0.32×0.20, 0.05) = 0.256
   balance     = 10000 − 20 = 9980
   ```

   Log style:

   ```text
   [BUY] Chicago D+1 2026-07-17 | 72.0-73.0F | $0.320 | EV +… | $… (HRRR)
   ```

   (Illustrative fill amounts assume EV/Kelly clear gates; under default σ=2 many mode books skip.)

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
            under partition residual model
```

Today’s strategy is essentially:

> Buy YES on the single bucket my point forecast lands in, with `p` = residual Gaussian mass for that bin. Enter only if EV vs ask clears `min_ev`, price/volume/spread pass, and portfolio caps allow.

That is a **forecast-tracking / favorite-bucket** strategy with honest residual probability — not multi-bucket EV shopping. Math detail: `MODEL.md`.

---

## Config knobs that matter most

| Key | Typical | Effect |
|-----|---------|--------|
| `min_ev` | 0.05 | Gate on model edge; strict vs uncalibrated wide σ |
| `max_price` | 0.45 | Never buy expensive favorites |
| `min_price` | 0.08 | Never buy penny / stub asks |
| `min_ask_depth_usd` | 25 | Min Gamma liquidity when reported (0 = off) |
| `stop_loss_pct` / `min_stop_width` | 0.20 / 0.05 | Stop = entry − max(pct×entry, width) |
| `max_bet` | 20 | Hard size cap (Kelly may bind first when edge is thin) |
| `max_slippage` | 0.03 | Reject wide books |
| `min_hours` / `max_hours` | 2 / 72 | Horizon window |
| `kelly_fraction` | 0.25 | Fraction of full Kelly |
| Portfolio caps | 20 / 2 / 6 / 20% | Concentration limits |
| `calibration_min` | 20 | Samples before city/source σ updates |
| `scan_interval` | 3600 | Full scan period (seconds) |
| `monitor_interval` | 600 | Stop/TP poll period (seconds) |

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
