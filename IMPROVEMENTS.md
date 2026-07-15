# WeatherBot — Potential Improvements

Brutal backlog of upgrades. Don't forget these just because paper PnL looked cute for a week.

Last updated: 2026-07-15

---

## Critical (fix or stay regarded)

### 1. Fix `bucket_prob` for normal buckets
**Current problem:** For regular 1° buckets, p is basically binary:
- forecast in bucket → p = 1.0
- forecast not in bucket → p = 0.0

Sigma only matters for edge buckets (`-999` / `999`). That means:
- EV math is fake
- Kelly sizes max out constantly
- Calibration barely affects the trades you actually take

**Fix:** Use a real normal CDF over the full bucket width for *all* buckets. Then sigma actually changes p, EV, and sizing.

### 2. Make calibration actually matter
Current calibration only tunes sigma after 30 resolved markets, and sigma barely feeds the main path.

**Improvements:**
- Lower `calibration_min` once you have quality data (or use hierarchical defaults earlier)
- Apply calibrated sigma to *every* probability estimate
- Track bias (signed error), not just MAE — forecasts can be systematically hot/cold by city
- Separate calibration by horizon (D+0 vs D+1 vs D+2)

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

### 5. Better entry filters
Current filters are fine but incomplete.

**Add:**
- Min liquidity / depth at ask (not just volume)
- Skip if orderbook is thin / fake mid
- Avoid ultra-narrow buckets when forecast uncertainty > bucket width
- Don't enter if market already heavily repriced toward your forecast

### 6. Resolution source audit
Polymarket resolves on specific stations/sources. Your bot assumes airport stations + Visual Crossing.

**Add:**
- Log official resolution criteria per market
- Compare assumed station vs actual resolution source
- Flag mismatches before they heem you

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

### 9. Live trading via official Polymarket `py-sdk` (not old `py-clob-client`)
`py-clob-client` is outdated. Current path is the official SDK:

- Repo: https://github.com/Polymarket/py-sdk
- Use that for auth, markets, orderbook, and order placement

Current weatherbot is still paper sim. When going live:

**Needs:**
- Swap stack to `py-sdk` (drop reliance on old `py-clob-client`)
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

### 12. Forecast change exits are crude
Current logic closes if forecast drifts far from entry bucket.

**Improve:**
- Recompute live EV; only exit if EV flipped negative
- Don't panic-close on tiny model noise
- Separate "model flip" vs "price dump" exits

### 13. Store more signal, less vibes
Already saves market JSON. Expand:
- Full orderbook snapshot at entry
- Competing bucket prices
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

After probability fix, re-tune these. If p is no longer binary 1.0, sizing behavior changes hard.

---

## Priority order (if we actually ship upgrades)

1. Fix `bucket_prob` + make sigma real
2. Portfolio caps / risk limits
3. Source blending + bias tracking
4. Resolution audit
5. Paper → live plumbing only after resolved track record

---

## Don't do

- Live YOLO before resolved sample size
- Trust unrealized PnL on open weather marks
- Add 20 cities before the math works on the current 20
- "AI rewrite the whole bot" without fixing the probability core

---

## Notes from first run (2026-07-15)

- Paper bot opened ~13 positions quickly
- Many buys at max bet because p≈1 under current math
- VC key works
- Continuous mode runs via `python bot_v2.py run`
- Self-learning exists, but is weak until probability model is fixed

If future-you is reading this: fix the math first, regard.
