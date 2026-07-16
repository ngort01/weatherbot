# AGENTS.md — Working on WeatherBet

Instructions for AI coding agents (and humans) making changes in this repo.

Deep product/architecture context: **`ARCHITECTURE.md`**.  
Backlog and known design traps: **`IMPROVEMENTS.md`**.  
Test philosophy: **`TESTING_PLAN.md`**.

---

## What this project is

- **Paper-trading bot** for Polymarket *highest temperature* markets.
- **One main module:** `weatherbet.py` (~1.2k lines). No package layout, no trading SDK.
- Reads forecasts (Open-Meteo, METAR) + Polymarket Gamma via `requests`; writes JSON under `data/`.
- **Does not place live orders.** Do not add live trading unless explicitly asked; if ever, follow `IMPROVEMENTS.md` §8–9 (official Polymarket `py-sdk`, env secrets, kill switch).

---

## Repo map

| Path | Role |
|------|------|
| `weatherbet.py` | All bot logic (config load, math, I/O, scan, monitor, CLI) |
| `config.json` | Strategy params (committed). Loaded **at import**. |
| `.env` / `.env.example` | Secrets only (`VC_KEY`). Never commit real keys. |
| `data/state.json` | Paper bankroll / W-L (runtime; gitignored patterns apply) |
| `data/markets/*.json` | One file per `{city}_{date}` market record |
| `data/calibration.json` | Per city/source σ and bias |
| `tests/` | Characterization tests (pin **current** behavior) |
| `ARCHITECTURE.md` | How the system works + dummy bet |
| `IMPROVEMENTS.md` | What is wrong / next, and traps not to step in |
| `TESTING_PLAN.md` | What tests should lock and why |
| `sim_dashboard_repost.html` | Unrelated/legacy dashboard asset — leave alone unless asked |

---

## Commands

Run from **repo root** (import loads `config.json` from cwd).

```bash
# venv if present
source .venv/bin/activate   # or: python -m venv .venv && pip install -r requirements-dev.txt

python weatherbet.py          # main loop (network + writes data/)
python weatherbet.py status
python weatherbet.py report

pip install -r requirements-dev.txt
pytest                        # default suite; must stay green
```

Runtime deps: `requests`, `python-dotenv` (see `requirements-dev.txt`).

---

## Non-negotiable invariants

Treat these as product rules until the user / IMPROVEMENTS explicitly change them.

1. **Paper only** — never debit a real wallet; never hardcode API secrets into `config.json` or source.
2. **Airport stations, not city centers** — `LOCATIONS[*].lat/lon/station` are resolution points. Do not “fix” to downtown coords.
3. **One position per market file** — `data/markets/{city}_{date}.json`; closed position blocks re-entry.
4. **Only the forecast-matched bucket is tradable** — scan does not shop other buckets for higher EV.
5. **Binary middle-bucket probability (today)** — `bucket_prob` returns `1.0` / `0.0` for non-edge ranges. Edge buckets (`-999` / `999`) use normal CDF + σ.
6. **Early exit ≠ double settle** — if `position.status` is already closed, resolution only annotates `resolved_outcome` / `hold_to_resolution_pnl`; do not credit bankroll again.
7. **Wins/losses in state** count held-to-resolution settlements, not stop/TP exits.
8. **Characterization tests document reality** — updating “wrong” math without updating tests and IMPROVEMENTS is a bug.

---

## Do NOT “fix” without an explicit product decision

These look like bugs; several are deliberate or trap-laden. Details: `IMPROVEMENTS.md` §1–2.

| Tempting change | Why not (or not naively) |
|-----------------|---------------------------|
| Continuous `Φ` over raw `[t_low, t_high]` for all buckets | Zero-width buckets (`be 80°F` → `(80,80)`) get **p=0** forever. Need discrete resolution bins. |
| Ship continuous CDF with default `SIGMA_F=2` | Mode bin mass ~20%; bot stops buying typical 30–45¢ favorites — strategy flip, not a free fix. |
| Make Kelly/EV “honest” without new `p` model | With `p∈{0,1}`, EV/Kelly mostly force `max_bet`. Either keep match-style sizing honestly, or rebuild partition probs. |
| Apply calibration σ to middle buckets only | Incomplete without bias, horizon splits, and partition scoring. |
| Hit live APIs in unit tests | Always mock `requests`; tests must pass offline. |
| Rewrite into a multi-package framework for purity | Out of scope unless asked; extract only when testing/change cost requires it. |

If you change trading semantics: update **`IMPROVEMENTS.md` status**, **`ARCHITECTURE.md`** if behavior/docs diverge, and **tests** in the same change.

---

## Import / config gotchas (break tests if ignored)

- `weatherbet.py` at import: `load_dotenv()`, reads `config.json`, sets module-level constants (`MAX_BET`, `MIN_EV`, …), creates `data/` dirs.
- Constants are **bound at import** — tests that need different limits should `monkeypatch` module attributes, not only edit a temp config after import.
- Storage tests use the `wb` fixture in `tests/conftest.py` (redirects `DATA_DIR` / `MARKETS_DIR` / `STATE_FILE` / `CALIBRATION_FILE` to `tmp_path`). Prefer that over writing into real `data/`.
- **Never run experimental code against production paper state** without isolating paths; real `data/` may hold multi-day paper history.

---

## How a full cycle works (short)

```text
run_loop
  ├─ every SCAN_INTERVAL (~1h): scan_and_update
  │     for 20 cities × 4 dates:
  │       forecasts → Gamma event → snapshots
  │       manage open (stop / forecast exit)
  │       maybe open (filters + risk caps)
  │     resolve via Gamma; actuals via Visual Crossing
  │     maybe run_calibration
  └─ else every MONITOR_INTERVAL (10m): monitor_positions
        stop / trailing / take-profit only
```

Entry filters (all must pass): volume, hours window, matched bucket, EV, min size, re-fetched ask/spread/slippage, `max_price`, portfolio risk.

Portfolio caps (`config.json`): `max_open_positions`, `max_open_per_city`, `max_open_per_date`, `max_capital_at_risk_pct`.

See **`ARCHITECTURE.md`** for the dummy bet and exit matrix.

---

## Coding conventions

- **Match existing style** in `weatherbet.py`: plain functions, section banners, minimal deps, no type-system rewrite.
- Prefer **small, testable pure functions** for new math/risk logic; keep network at the edges.
- Logs use tags like `[BUY]`, `[SKIP]`, `[RISK]`, `[STOP]`, `[CAL]` — keep that pattern for greppability.
- User-facing docs: complete sentences; no drive-by markdown trees the user did not ask for.
- Do **not** commit:
  - `.env` secrets
  - Large regenerated paper dumps unless the user wants them
  - Unrelated refactors bundled with a behavior change

### When changing behavior

1. Read the relevant section of `ARCHITECTURE.md` + `IMPROVEMENTS.md`.
2. Add/adjust **characterization or unit tests first** when possible.
3. Implement the minimal code change in `weatherbet.py` (or extract only what you must).
4. Run `pytest`.
5. Note status updates in `IMPROVEMENTS.md` if closing a backlog item.

### When only documenting

Update the smallest set of docs that stay true. Prefer linking over duplicating long math.

---

## Testing expectations

- Suite is **characterization-first**: assert what the code does *now*, including binary `p`.
- Mark or comment quirks that IMPROVEMENTS plans to change (e.g. reference §1).
- Pure functions first; mock network; use `wb` fixture for disk.
- Config-dependent sizing tests depend on committed `config.json` values — pin or patch explicitly.
- Do not expand scope into full `scan_and_update` integration tests unless needed; they are heavy and network-shaped.

```bash
pytest
# or focused:
pytest tests/test_bucket_prob.py tests/test_ev_kelly_sizing.py -q
```

---

## Secrets and safety

| Item | Where |
|------|--------|
| `VC_KEY` | `.env` only |
| Strategy params | `config.json` |
| Paper balances / positions | `data/` (local runtime) |

Destructive ops (delete `data/`, force-push, live keys) need explicit user intent. Prefer reversible local edits.

Do not print or commit contents of `.env`.

---

## Product decisions still open (context for PRs)

Not blockers for small fixes; do not implement unless asked:

1. Probabilistic partition model vs honest match-style sizing (`IMPROVEMENTS` §1).
2. Calibration actually driving middle-bin `p` / sizing (§2).
3. Correlation haircut beyond hard open caps (§3).
4. Source blending, better entry filters, fee-aware paper fills (§4–7).
5. Live trading (§8–9) — explicit go-live criteria exist; do not soft-launch.

---

## Quick “where do I edit?”

| Goal | Start here |
|------|------------|
| Probability / EV / Kelly | `bucket_prob`, `calc_ev`, `calc_kelly`, `bet_size` |
| Entry / exit trading rules | `scan_and_update`, `monitor_positions` |
| Risk caps | `portfolio_snapshot`, `risk_limit_reason`, `config.json` |
| Forecast sources | `get_ecmwf`, `get_hrrr`, `get_metar`, `take_forecast_snapshot` |
| Markets / buckets | `get_polymarket_event`, `parse_temp_range`, `in_bucket` |
| Resolution / actuals | `check_market_resolved`, `get_actual_temp` |
| Calibration | `run_calibration`, `get_sigma`, `snapshot_source_temp` |
| Persistence | `load_market` / `save_market` / `load_state` / `new_market` |
| Cities / stations | `LOCATIONS`, `TIMEZONES` |

---

## Definition of done (agent checklist)

- [ ] Behavior matches user request; no silent strategy flips
- [ ] `pytest` green
- [ ] No secrets in commits; config vs `.env` boundary respected
- [ ] Tests updated if characterization surface changed
- [ ] `IMPROVEMENTS.md` / `ARCHITECTURE.md` touched only when they would otherwise lie
- [ ] Real `data/` paper state not clobbered by tests or experiments
