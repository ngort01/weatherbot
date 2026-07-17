# WeatherBet — Probability, EV, and Kelly

Canonical math reference for `weatherbet/model.py`.

**System flow / dummy bet:** `ARCHITECTURE.md`  
**Product traps & redesign history:** `IMPROVEMENTS.md` §1–2  
**Tests:** `tests/test_bucket_prob.py`, `tests/test_ev_kelly_sizing.py`

---

## Overview

Entry sizing uses three pure steps:

1. **`bucket_prob`** — model probability `p` that the matched temperature bucket wins
2. **`calc_ev`** — expected value of a YES share at market `price`
3. **`calc_kelly` → `bet_size`** — fractional Kelly fraction of bankroll, then dollar cap

Config knobs (from `config.json`, bound on `weatherbet.config` at import):

| Constant | Config key | Typical default |
|----------|------------|-----------------|
| `KELLY_FRACTION` | `kelly_fraction` | `0.25` (quarter Kelly) |
| `MAX_BET` | `max_bet` | `20.0` |
| `MIN_EV` | `min_ev` | `0.05` (retuned for partition `p`) |

**Product (Option B):** residual high ~ `N(μ, σ²)` with μ = forecast − bias. Still **only the forecast-matched bucket is tradable**; `p` is that bin’s continuous mass, not binary certainty.

---

## `norm_cdf(x)`

Standard normal CDF via `math.erf`:

```text
Φ(x) = 0.5 × (1 + erf(x / √2))
```

---

## `resolution_bin(t_low, t_high)`

Maps a parsed Polymarket range to continuous support under **integer-degree** resolution. Adjacent buckets form a partition of ℝ:

| Market range (parsed) | Continuous support |
|------------------------|--------------------|
| Exact `be v` → `(v, v)` | `[v − 0.5, v + 0.5)` |
| Between `a–b` | `[a − 0.5, b + 0.5)` |
| `or below` `T` → `(-999, T)` | `(-∞, T + 0.5)` |
| `or higher` `T` → `(T, 999)` | `[T − 0.5, +∞)` |

This fixes zero-width buckets: integrating a continuous density over a point would give `p = 0`; half-unit expansion gives positive mode mass.

---

## `bucket_prob(forecast, t_low, t_high, sigma=None, bias=0.0)`

```text
μ = forecast − bias
σ = max(sigma or 2.0, 1e-6)
(lo, hi) = resolution_bin(t_low, t_high)
p = Φ((hi − μ) / σ) − Φ((lo − μ) / σ)
```

(with Φ(+∞) = 1, Φ(−∞) = 0; result clamped to `[0, 1]`).

| Input | Source |
|-------|--------|
| `forecast` | Best point forecast (°F or °C) |
| `sigma` | Prefer `get_sigma(city, source)` — calibrated MAE, else `SIGMA_F` (°F) / `SIGMA_C` (°C). If omitted, `bucket_prob` defaults to **`SIGMA_F` only** (pure helper; °C callers must pass σ). |
| `bias` | `get_bias(city, source)` — mean(forecast − actual), else `0` |

### Worked examples

**Exact bin, uncalibrated σ=2, forecast on mode:**

```text
bucket_prob(80, 80, 80, sigma=2) = Φ(0.25) − Φ(−0.25) ≈ 0.197
```

At ask `0.35`: `EV ≈ 0.197/0.35 − 1 ≈ −0.44` → skip under `min_ev`.

**2° range, σ=2, forecast mid-bin:**

```text
bucket_prob(72.5, 72, 73, sigma=2) = Φ(1) − Φ(−1) ≈ 0.683
```

**Bias:** positive bias (warm forecasts) lowers μ → more mass on cooler bins.

### `event_bucket_probs`

Scores every range in an event; optional renormalize so Σp = 1. Used for tests / future multi-bucket work. Entry still picks the matched bin only.

---

## `calc_ev(p, price)`

Expected net return per $1 of stake if you buy YES at `price` (pays $1 if the bucket wins):

```text
EV = p × (1/price − 1) − (1 − p)
```

| Case | Result |
|------|--------|
| `price ≤ 0` or `price ≥ 1` | `0.0` |
| Fair price (`price = p`) | `0` |
| `p = 0.197`, ask `0.35` | deeply negative |

Entry requires `EV ≥ min_ev`.

---

## `calc_kelly(p, price)`

Odds against a $1 stake (net profit if you win):

```text
b = 1/price − 1
f* = (p·b − (1 − p)) / b
calc_kelly = min(max(0, f*) × kelly_fraction, 1.0)
```

With realistic `p < 1`, fractional Kelly often sizes **below** `max_bet` on large bankrolls when edge is thin.

---

## `bet_size(kelly, balance)`

```text
size = min(kelly × balance, max_bet)
```

Rounded to cents.

---

## How it behaves in practice

```text
match middle bin → p = mode mass under N(μ,σ²)  (often 0.2–0.7)
                 → EV positive only if p is high enough vs ask
                 → kelly scales with edge; max_bet still caps
```

Strategy one-liner:

> Forecast-tracking: buy YES on the single bucket the point forecast lands in, sized by real residual probability vs market price — not by treating the match as certain.

`in_bucket` still decides **which** bucket is matched and forecast-exit drift; it does not set `p`.

---

## Related code map

| Symbol | Module |
|--------|--------|
| `norm_cdf`, `resolution_bin`, `bucket_prob`, `event_bucket_probs`, `calc_ev`, `calc_kelly`, `bet_size` | `weatherbet/model.py` |
| `in_bucket`, `parse_temp_range` | `weatherbet/polymarket.py` |
| `consider_entry` (uses p / EV / Kelly) | `weatherbet/entry.py` |
| Portfolio open caps (not Kelly) | `weatherbet/risk.py` |
| σ / bias from residuals | `weatherbet/calibration.py` |
