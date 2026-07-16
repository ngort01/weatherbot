# WeatherBot — Potential Improvements

Brutal backlog of upgrades. Don't forget these just because paper PnL looked cute for a week.

Last updated: 2026-07-16

---

## Critical (fix or stay regarded)

### 1. Probability model — don't "fix" it with a naive continuous CDF

**What the code does today:** For regular buckets, `bucket_prob` is binary:

- forecast in bucket → `p = 1.0`
- forecast not in bucket → `p = 0.0`

Sigma only matters for edge buckets (`-999` / `999`). Entry only considers the single matched bucket. Consequences:

- EV math is fake (matched trades always look great)
- Kelly sizes max out constantly (`p≈1` → fractional Kelly → `max_bet`)
- Calibration barely affects the trades you actually take

**That is not an accident with zero upside.** Two real constraints kill the naive rewrite:

#### Trap A — zero-width buckets

`"be 80°F"` parses as `(t_low, t_high) = (80, 80)`.

Naive continuous interval prob:

```text
p = Φ((t_high - μ) / σ) - Φ((t_low - μ) / σ)
```

with equal bounds is **always 0**. A bot that "fixed" binary this way would never trade exact-temp markets. Resolution is discrete (rounded degrees); point buckets need **positive-measure bins** (e.g. half-unit: `[v-0.5, v+0.5)`), not a continuous integral over a point.

#### Trap B — default σ=2 vs Polymarket mode prices

Even with a proper 1° window, a normal with default `SIGMA_F = 2.0` puts only ~**20%** mass in the peak bin:

```text
2·Φ(0.5/2) - 1 ≈ 0.197
```

Polymarket often prices the favorite bucket around **30–45¢**. Then:

```text
EV ≈ p/price - 1 = 0.197/0.35 - 1 ≈ -0.44
```

A "statistically pure" bot with uncalibrated σ=2 would conclude **every middle bucket is massively overpriced**, refuse standard mode trades, and only touch tails (`or higher` / `or below`) or absurdly cheap bins. That is a full strategy flip — not a free bugfix.

| Model | Implicit claim | Behavior |
|-------|----------------|----------|
| Binary `p∈{0,1}` | Point-forecast match = certainty | Buys 30–45¢ favorites hard; max bet |
| Normal σ=2 on 1° bins | Residual error ~2°F Gaussian | Hates those favorites; mostly idle on middles |
| Market ~35¢ on mode | ~σ≈1.1 if Gaussian | Between the two extremes |

Binary is **max overconfidence**. Naive continuous with default σ is **structural underconfidence vs how these books are priced** (or correctly skeptical only *if* true residual error really is ~2°F).

#### What to do instead

**Do not** paste continuous CDF over raw `[t_low, t_high]` and ship.

Pick an honest design:

1. **Probabilistic path (real EV/Kelly):**
   - Map every outcome to a resolution-aware bin (exact °F → half-unit or official rounding rule; between-ranges → correct inclusive integers; tails → half-lines)
   - Score the **full partition** so probs sum ~1 across the event
   - Use horizon- and city-dependent **calibrated** σ + bias — not global `SIGMA_F = 2.0`
   - Only then compare model `p` to market price; accept that trade set may shrink or shift to tails if markets are overconfident

2. **Match-style path (current product, honest about it):**
   - Keep "enter the bin my point forecast lands in" as a filter
   - Stop pretending Kelly/EV mean much when `p∈{0,1}`
   - Size with fixed/fractional rules and risk caps, not fake certainty

Either way: **calibration of residual error is the product**, not "continuous vs binary" as a slogan.

### 2. Make calibration actually work (this is the real math core)

Current calibration only tunes sigma after 30 resolved markets, and sigma barely feeds the main path for middle buckets.

**Worse than the doc used to admit:** `get_actual_temp()` (Visual Crossing) exists but is **never called** on resolve. `actual_temp` stays `None`, so residual MAE never fills. Self-learning is dead code until that is wired.

**Improvements:**

- Actually record official/assumed station temps on resolution
- Lower `calibration_min` once you have quality data (or use hierarchical defaults earlier)
- Apply calibrated σ **and bias** to every probability estimate (if on probabilistic path)
- Track bias (signed error), not just MAE — forecasts can be systematically hot/cold by city
- Separate calibration by horizon (D+0 vs D+1 vs D+2)
- Report model-implied mode mass vs market mode price (are you σ=2 or is the book σ≈1?)

### 3. Portfolio / correlation risk

13 open weather bets can all die on the same air mass.

**Add:**

- Max open positions total
- Max open per city
- Max open per date
- Max total capital at risk (% of bankroll)
- Correlation haircut when multiple cities share the same weather regime

---

## High ROI (degen upgrades that actually print or stop bleed)

### 4. Source blending, not single "best source"

Don't just pick HRRR or ECMWF. Blend them with learned weights.

Example:

- US D+0/D+1: heavier HRRR/METAR
- EU/Asia: heavier ECMWF
- Late horizon: decay confidence harder

Blending only pays after residuals are honest; otherwise you're averaging garbage into μ.

### 5. Better entry filters

Current filters are fine but incomplete.

**Add:**

- Min liquidity / depth at ask (not just volume)
- Skip if orderbook is thin / fake mid
- Avoid ultra-narrow buckets when forecast uncertainty > bucket width (only meaningful once σ is real)
- Don't enter if market already heavily repriced toward your forecast
- Note: scan path still treats `outcomePrices` like bid/ask; real bid/ask is only re-fetched at entry — thin-book risk is real

### 6. Resolution source audit

Polymarket resolves on specific stations/sources. Your bot assumes airport stations + Visual Crossing for actuals (and Polymarket close for win/loss).

**Add:**

- Log official resolution criteria per market
- Compare assumed station vs actual resolution source
- Flag mismatches before they heem you
- This also defines the correct discrete binning for item 1

### 7. Fees / slippage realism

Paper fills at ask are fantasy.

**Add:**

- Assume worse fill than mid/ask
- Model taker fees if/when live
- Track theoretical vs realistic PnL separately

---

## Live Trading (only after paper proof)

### 8. Don't go live on vibes

Require before real money:

- 50+ resolved trades minimum
- Win rate + EV by city/source/horizon
- Stop-loss and forecast-change exits reviewed
- No giant unrealized mark-to-market cope

### 9. Live trading via official Polymarket `py-sdk`

Current weatherbot is **paper only** and talks to Gamma via plain `requests` — there is **no** `py-clob-client` dependency to remove. When going live, use the official stack:

- Repo: https://github.com/Polymarket/py-sdk
- Auth, markets, orderbook, order placement

**Needs:**

- Add `py-sdk` for live path (keep paper path on requests if useful)
- Wallet / API key handling via env (not hardcoded)
- Order placement + cancel logic
- Partial fill handling
- Position reconciliation vs Polymarket state
- Kill switch

### 10. Secrets hygiene

**Done (2026-07-15):** `VC_KEY` moved to `.env`. `config.json` is strategy params only.
`.env` is gitignored. Use `.env.example` as the template.

---

## Data / Learning upgrades

### 11. Richer self-learning

Beyond sigma MAE:

- City win rate
- Source win rate
- Bucket-width performance
- Time-of-day / lead-time performance
- Auto-downweight cities that suck
- Model-vs-market calibration plots (mode mass vs favorite price)

### 12. Forecast change exits are crude

Current logic closes if forecast drifts far from entry bucket.

**Improve:**

- Recompute live EV; only exit if EV flipped negative (requires a real `p` model)
- Don't panic-close on tiny model noise
- Separate "model flip" vs "price dump" exits

### 13. Store more signal, less vibes

Already saves market JSON. Expand:

- Full orderbook snapshot at entry
- Competing bucket prices (full event book)
- Which source would have won ex-post
- Post-resolution attribution report

---

## Ops / Quality of life

### 14. CLI that matches reality

README says `weatherbet.py`; repo has `bot_v2.py`.
No true one-shot `scan` command — only `run|status|report`.

**Add:**

- `python bot_v2.py scan` (single cycle, exit)
- Consistent naming
- Better logging levels

### 15. Monitoring

Background process is fine, but:

- Heartbeat / last-scan timestamp
- Alert on repeated API failures
- Daily report of resolved PnL only (ignore open mark noise)

### 16. Config defaults sanity check

Current-ish defaults:

- `min_ev: 0.1`
- `max_price: 0.45`
- `max_bet: 20`
- `kelly_fraction: 0.25`
- `SIGMA_F: 2.0` / `SIGMA_C: 1.2` (code constants)

If you move to probabilistic `p`:

- Re-tune hard — mode mass may be ~20–40%, not 1.0; sizing and EV gates change completely
- Do **not** keep `min_ev` / Kelly settings that only made sense under binary certainty
- If you stay match-style, drop or relabel fake EV/Kelly and size with explicit caps

---

## Priority order (if we actually ship upgrades)

1. **Decide strategy honesty:** probabilistic book vs match-style filter — then implement that, not a slogan CDF
2. **Wire resolution actuals + residual calibration** (bias, σ, horizon) — dead without this
3. **If probabilistic:** resolution-aware bins + full-event scoring; only then EV/Kelly mean something
4. Portfolio caps / risk limits (needed either path — binary currently stacks correlated max bets)
5. Source blending after residuals are real
6. Resolution source audit (defines bins + avoids station heems)
7. Paper → live via `py-sdk` only after resolved track record

---

## Don't do

- Live YOLO before resolved sample size
- Trust unrealized PnL on open weather marks
- Add 20 cities before the math works on the current 20
- "AI rewrite the whole bot" without deciding the probability product
- **Naive continuous CDF on raw `[t_low, t_high]`** — bricks zero-width buckets (`p=0`)
- **Uncalibrated σ=2 continuous "fix"** — systematically refuses 30–45¢ mode buckets; full strategy flip by accident
- Pretend Kelly is risk management while `p=1` on every match

---

## Notes from first run (2026-07-15)

- Paper bot opened ~13 positions quickly
- Many buys at max bet because `p≈1` under current math
- VC key works
- Continuous mode runs via `python bot_v2.py run`
- Self-learning exists in name only until actuals + residual wiring work

## Notes from review (2026-07-16)

- Binary `p` is max overconfidence, not a clever discrete model
- Continuous CDF without discrete bins is wrong for exact-temp markets
- Continuous with default σ=2 fights typical Polymarket favorite prices (~30–45¢ vs ~20% model mass)
- Market-implied σ for mode bins is closer to ~1.1°F if Gaussian — calibrate, don't assume 2.0
- Repo has no `py-clob-client`; live path is greenfield `py-sdk` + env secrets

If future-you is reading this: pick an honest probability product, calibrate residuals, then size. Don't paste CDF and call it fixed, regard.
