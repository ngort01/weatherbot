# WeatherBet — Probability, EV, and Kelly

This is the math pin. If code and this file disagree, **fix one of them** — don't freestyle a third version in a PR description.

**System flow / dummy bet:** `ARCHITECTURE.md`  
**Traps, redesign history, "don't regress" list:** `IMPROVEMENTS.md` §1–2  
**Tests that lock this:** `tests/test_bucket_prob.py`, `tests/test_ev_kelly_sizing.py`, `tests/test_forecast_exit.py`

---

## Overview

Entry sizing is three pure steps. No vibes, no "the forecast matched so p=1":

1. **`bucket_prob`** — model `p` that the **matched** temp bucket wins under residual Gaussian mass
2. **`calc_ev`** — EV of a YES share at market `price`
3. **`calc_kelly` → `bet_size`** — fractional Kelly of bankroll, then hard dollar cap

Config knobs (`config.json` → `weatherbet.config` at import):

| Constant | Config key | Typical default |
|----------|------------|-----------------|
| `KELLY_FRACTION` | `kelly_fraction` | `0.25` (quarter Kelly — not full-send) |
| `MAX_BET` | `max_bet` | `20.0` |
| `MIN_EV` | `min_ev` | `0.05` (retuned when binary p died) |

**Product (Option B):** residual high ~ `N(μ, σ²)` with μ = forecast − bias. Still **only the forecast-matched bucket is tradable**. `p` is that bin's continuous mass — not binary certainty, not shopping the rest of the event for juicier EV.

---

## `norm_cdf(x)`

Standard normal CDF via `math.erf`. Boring. Correct.

```text
Φ(x) = 0.5 × (1 + erf(x / √2))
```

---

## `resolution_bin(t_low, t_high)`

Polymarket resolves on **integer degrees**. Parsed ranges need continuous support so a density can actually put mass somewhere.

Adjacent buckets partition ℝ. Half-unit edges, not raw equal bounds:

| Market range (parsed) | Continuous support |
|------------------------|--------------------|
| Exact `be v` → `(v, v)` | `[v − 0.5, v + 0.5)` |
| Between `a–b` | `[a − 0.5, b + 0.5)` |
| `or below` `T` → `(-999, T)` | `(-∞, T + 0.5)` |
| `or higher` `T` → `(T, 999)` | `[T − 0.5, +∞)` |

**Trap A (don't regress):** integrate a continuous density over a point → `p = 0` forever. Exact `"be 80°F"` is `(80, 80)`. Half-unit expansion is how mode mass exists at all. Naive Φ(hi)−Φ(lo) on raw equal bounds is regarded, not rigorous.

---

## `bucket_prob(forecast, t_low, t_high, sigma=None, bias=0.0)`

```text
μ = forecast − bias
σ = max(sigma or 2.0, 1e-6)
(lo, hi) = resolution_bin(t_low, t_high)
p = Φ((hi − μ) / σ) − Φ((lo − μ) / σ)
```

Φ(+∞) = 1, Φ(−∞) = 0; result clamped to `[0, 1]`.

| Input | Source |
|-------|--------|
| `forecast` | Best point forecast (°F or °C) |
| `sigma` | Prefer `get_sigma(city, source)` — calibrated MAE, else `SIGMA_F` / `SIGMA_C`. Omitted → helper defaults to **`SIGMA_F` only**. °C callers must pass σ or they price in the wrong units. |
| `bias` | `get_bias(city, source)` — mean(forecast − actual), else `0`. Sign is not decorative: μ = forecast − bias |

### Worked examples

**Exact bin, uncalibrated σ=2, forecast on mode (Trap B poster child):**

```text
bucket_prob(80, 80, 80, sigma=2) = Φ(0.25) − Φ(−0.25) ≈ 0.197
```

At ask `0.35`: `EV ≈ 0.197/0.35 − 1 ≈ −0.44` → skip under `min_ev`.  
That's not a bug. Uncalibrated σ=2 systematically hates 30–45¢ favorites. Binary-era fill rates under default σ are hopium.

**2° range, σ=2, forecast mid-bin:**

```text
bucket_prob(72.5, 72, 73, sigma=2) = Φ(1) − Φ(−1) ≈ 0.683
```

**Bias:** positive bias (warm forecasts) lowers μ → more mass on cooler bins. Flip the residual sign and you're pricing the wrong side of the station.

### `event_bucket_probs`

Scores every range in an event; optional renormalize so Σp = 1. Tests / future multi-bucket EV shopping. **Entry still only touches the matched bin.** Don't "fix" that without a product decision.

---

## `calc_ev(p, price)`

Expected net return per $1 of stake buying YES at `price` (pays $1 if the bucket wins):

```text
EV = p × (1/price − 1) − (1 − p)
```

| Case | Result |
|------|--------|
| `price ≤ 0` or `price ≥ 1` | `0.0` (garbage book → no edge story) |
| Fair price (`price = p`) | `0` |
| `p = 0.197`, ask `0.35` | deeply negative — market is not "cheap," you're underconfident or the book is right |

Entry requires `EV ≥ min_ev`. Edge first; narrative later.

---

## `calc_kelly(p, price)`

Odds against a $1 stake (net profit if you win):

```text
b = 1/price − 1
f* = (p·b − (1 − p)) / b
calc_kelly = min(max(0, f*) × kelly_fraction, 1.0)
```

With realistic `p < 1`, fractional Kelly often sizes **below** `max_bet` on a fat bankroll when edge is thin. That's the feature. Full Kelly on weather residuals is how you get heemed by correlated cities.

---

## `bet_size(kelly, balance)`

```text
size = min(kelly × balance, max_bet)
```

Rounded to cents. Kelly proposes; `max_bet` is the leash.

---

## How it behaves in practice

```text
match middle bin → p = mode mass under N(μ,σ²)  (often 0.2–0.7)
                 → EV positive only if p is high enough vs ask
                 → kelly scales with edge; max_bet still caps
```

Strategy one-liner:

> Forecast-tracking: buy YES on the **single** bucket the point forecast lands in, sized by real residual probability vs market price — not by treating the match as certain.

`in_bucket` still decides **which** bucket is matched and the **first** forecast-exit gate (left bucket + ° buffer). It does **not** set `p`. Binary p was max overconfidence cosplay.

### Forecast exit residual edge

Forecast left the bucket+buffer? Don't panic-sell just because the mode moved. Scan recomputes live `p` on the **held** bucket vs salvage bid:

```text
edge = p − bid
edge_gone if edge ≤ forecast_exit_min_edge   (default 0)
else hold                                    # [HOLD] residual edge — diamond hands with math

# hysteresis (config forecast_exit_confirm_scans; committed default 1 = off):
close only after N consecutive edge_gone scans
reset hits on residual hold or forecast back in bucket+buffer

# near resolution (hours_left < forecast_exit_fast_hours, default 6):
N = 1  # do not wait another hourly scan into dust
```

Helpers: `residual_edge`, `should_exit_on_forecast`, `forecast_exit_confirm_needed`,
`bump_forecast_exit_hits`. Price stops (stop / trail / TP) are a different path —
residual edge doesn't replace them.

Note: the second confirm scan does **not** require the forecast to change again —
only that residual edge is still gone (`p ≤ bid`). Bids can reprice without a
new model run; global models often only re-run a few times per day.

---

## Related code map

| Symbol | Module |
|--------|--------|
| `norm_cdf`, `resolution_bin`, `bucket_prob`, `event_bucket_probs`, `calc_ev`, `calc_kelly`, `bet_size`, `residual_edge`, `should_exit_on_forecast`, `forecast_exit_confirm_needed`, `bump_forecast_exit_hits` | `weatherbet/model.py` |
| `in_bucket`, `parse_temp_range` | `weatherbet/polymarket.py` |
| `consider_entry` (uses p / EV / Kelly) | `weatherbet/entry.py` |
| Forecast exit residual-edge + hysteresis | `weatherbet/scan.py` (`forecast_exit_confirm_needed`, `bump_forecast_exit_hits`) |
| Portfolio open caps (not Kelly — correlation still open) | `weatherbet/risk.py` |
| σ / bias from residuals | `weatherbet/calibration.py` |

If future-you is about to "simplify" `bucket_prob` back to raw equal-bound CDF: read Trap A in `IMPROVEMENTS.md` first, then don't.
