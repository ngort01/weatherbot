# WeatherBet — Probability, EV, and Kelly

Canonical math reference for `weatherbet/model.py`.

**System flow / dummy bet:** `ARCHITECTURE.md`  
**Product traps & redesign forks:** `IMPROVEMENTS.md` §1–2  
**Characterization tests:** `tests/test_bucket_prob.py`, `tests/test_ev_kelly_sizing.py`

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
| `MIN_EV` | `min_ev` | `0.10` |

---

## `norm_cdf(x)`

Standard normal CDF via `math.erf`:

```text
Φ(x) = 0.5 × (1 + erf(x / √2))
```

Used only for **edge** buckets in `bucket_prob`.

---

## `bucket_prob(forecast, t_low, t_high, sigma=None)`

| Bucket type | How `p` is computed |
|-------------|---------------------|
| Middle / exact (`72–73` or `80` → `(80,80)`) | **Binary:** forecast in range → `1.0`, else `0.0` |
| Lower edge (`t_low == -999`, “or below”) | `Φ((t_high − forecast) / σ)` |
| Upper edge (`t_high == 999`, “or higher”) | `1 − Φ((t_low − forecast) / σ)` |

- Default `σ = 2.0` if omitted (callers may pass calibration σ).
- Middle-bin match uses `in_bucket` (zero-width exact bins: rounded forecast equals the point).
- **Mode trades** (forecast lands in a middle bin) always get **`p = 1.0`**. σ does not affect them.

This is deliberate product state today — not continuous interval probability. Naive rewrites break zero-width bins or flip the strategy; see `IMPROVEMENTS.md` §1.

---

## `calc_ev(p, price)`

Expected net return per $1 of stake if you buy YES at `price` (pays $1 if the bucket wins):

```text
EV = p × (1/price − 1) − (1 − p)
```

| Case | Result |
|------|--------|
| `price ≤ 0` or `price ≥ 1` | `0.0` |
| `p = 1`, ask `0.32` | `1/0.32 − 1 = +2.125` (clears typical `min_ev`) |
| Fair price (`price = p`) | `0` |

Entry requires `EV ≥ min_ev`. With binary `p = 1` and ask under `max_price`, EV is almost always large and positive.

---

## `calc_kelly(p, price)`

Kelly criterion: fraction of bankroll that maximizes long-run log growth given win probability `p` and decimal odds from the YES price.

Odds against a $1 stake (net profit if you win):

```text
b = 1/price − 1
```

Full Kelly fraction:

```text
f* = (p·b − (1 − p)) / b
```

This implementation then:

1. Rejects invalid prices (`≤ 0` or `≥ 1`) → `0.0`
2. Floors negative `f*` at `0` (no short / no forced bet)
3. Multiplies by **`kelly_fraction`** (fractional Kelly; default quarter)
4. Caps at `1.0` (never more than 100% of bankroll as a fraction)
5. Rounds to 4 decimals

```text
calc_kelly = min(max(0, f*) × kelly_fraction, 1.0)
```

| Inputs | Result (with `kelly_fraction=0.25`) |
|--------|--------------------------------------|
| `p=1`, any valid price | `0.25` (full Kelly is 1.0 × 0.25) |
| `p=0.5`, `price=0.5` | `0.0` (no edge) |
| `p=0.1`, `price=0.5` | `0.0` (negative edge floored) |

---

## `bet_size(kelly, balance)`

```text
size = min(kelly × balance, max_bet)
```

Rounded to cents. Under binary `p = 1`, fractional Kelly is typically `0.25`, so on any non-tiny bankroll the **binding constraint is `max_bet`**, not Kelly.

Example: `kelly=0.25`, `balance=10000` → raw `$2500` → capped to **`$20`**.

---

## How it behaves in practice

```text
match middle bin → p = 1
                 → EV huge if ask < 1
                 → kelly ≈ kelly_fraction
                 → size ≈ max_bet (if cash allows)
```

So today EV/Kelly mostly act as **gates that almost always pass** on matched middle buckets; real controls are `max_price`, volume, hours, slippage, and portfolio risk caps (`risk.py` / `ARCHITECTURE.md`).

Strategy one-liner:

> Forecast-tracking / favorite-bucket: treat the matched point-forecast bin as certain, buy YES if the book is cheap enough and risk caps allow.

If you change `p` to a real partition model, re-tune `min_ev` / Kelly / `max_bet` — they were calibrated under certainty. Product forks: `IMPROVEMENTS.md` §1.

---

## Related code map

| Symbol | Module |
|--------|--------|
| `norm_cdf`, `bucket_prob`, `calc_ev`, `calc_kelly`, `bet_size` | `weatherbet/model.py` |
| `in_bucket`, `parse_temp_range` | `weatherbet/polymarket.py` |
| `consider_entry` (uses p / EV / Kelly) | `weatherbet/entry.py` |
| Portfolio open caps (not Kelly) | `weatherbet/risk.py` |
| σ / bias from residuals | `weatherbet/calibration.py` |
