# AGENTS.md — Working on WeatherBet

Instructions for AI coding agents (and humans) making changes in this repo.

Deep product/architecture context: **`ARCHITECTURE.md`**.  
Probability / EV / Kelly math: **`MODEL.md`**.  
Backlog and known design traps: **`IMPROVEMENTS.md`**.  
Test philosophy: **`TESTING_PLAN.md`**.

---

## What this project is

- **Paper-trading bot** for Polymarket *highest temperature* markets.
- **Package layout:** `weatherbet/` modules + thin `weatherbet.py` launcher. No trading SDK.
- Reads forecasts (Open-Meteo, METAR) + Polymarket Gamma via `requests`; writes JSON under `data/`.
- **Does not place live orders.** Do not add live trading unless explicitly asked; if ever, follow `IMPROVEMENTS.md` §8–9 (official Polymarket `py-sdk`, env secrets, kill switch).

---

## Repo map

| Path | Role |
|------|------|
| `weatherbet.py` | Thin CLI launcher (`python weatherbet.py …`) |
| `weatherbet/` | Package: config, model, forecasts, polymarket, storage, state, risk, entry, scan, monitor, report, cli |
| `config.json` | Strategy params (committed). Loaded **at import** by `weatherbet.config`. |
| `.env` / `.env.example` | Secrets only (`VC_KEY`). Never commit real keys. |
| `data/state.json` | Paper bankroll / portfolio KPIs (runtime; gitignored) |
| `data/markets/*.json` | One file per `{city}_{date}` market record |
| `data/calibration.json` | Per city/source σ and bias |
| `tests/` | Characterization tests (pin **current** behavior) |
| `ARCHITECTURE.md` | How the system works + dummy bet |
| `MODEL.md` | Probability, EV, Kelly formulas (as implemented) |
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
python weatherbet.py scan     # dry-run: show markets + would-be trades (no fills/writes)
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
5. **Partition probability (Option B)** — `bucket_prob` uses a Gaussian residual over resolution-aware bins (`resolution_bin`: half-degree edges so exact °F bins have mass). σ + bias from calibration when present. Still only the **forecast-matched** bucket is tradable. Formulas: **`MODEL.md`**.
6. **Early exit ≠ double settle** — if `position.status` is already closed, resolution only annotates `resolved_outcome` / `hold_to_resolution_pnl`; do not credit bankroll again.
7. **Wins/losses in state** count held-to-resolution settlements, not stop/TP exits.
8. **Characterization tests document reality** — updating “wrong” math without updating tests, `MODEL.md`, and IMPROVEMENTS is a bug.

---

## Do NOT “fix” without an explicit product decision

These look like bugs; several are deliberate or trap-laden. Details: `IMPROVEMENTS.md` §1–2.

| Tempting change | Why not (or not naively) |
|-----------------|---------------------------|
| Continuous `Φ` over raw `[t_low, t_high]` without half-unit expand | Zero-width buckets (`be 80°F` → `(80,80)`) get **p=0**. Use `resolution_bin` (implemented). |
| Expect binary-era fill rates under default σ=2 | Mode mass ~20% on 1° bins; many 30–45¢ favorites fail `min_ev` until calibrated σ tightens — intentional. |
| Shop other buckets for higher EV | Still **matched-bucket only** unless product decision changes. |
| Apply σ without bias / wrong residual sign | Bias is mean(forecast − actual); μ = forecast − bias. |
| Hit live APIs in unit tests | Always mock `requests`; tests must pass offline. |
| Rewrite into a multi-package framework for purity | Out of scope unless asked; extract only when testing/change cost requires it. |

If you change trading semantics: update **`IMPROVEMENTS.md` status**, **`MODEL.md`** / **`ARCHITECTURE.md`** if behavior/docs diverge, and **tests** in the same change.

---

## Import / config gotchas (break tests if ignored)

- `weatherbet.config` at import: `load_dotenv()`, reads `config.json`, sets constants (`MAX_BET`, `MIN_EV`, …), creates `data/` dirs. Package `__init__` re-exports them for `import weatherbet as wb`.
- Constants live on **`weatherbet.config`** — code reads `config.MAX_BET` etc. Tests that need different limits should use the `patch_config` fixture (or patch both `weatherbet.config` and the package alias), not only edit a temp config after import.
- Storage tests use the `wb` fixture in `tests/conftest.py` (redirects paths on `config` + package; resets `calibration._cal`). Prefer that over writing into real `data/`.
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
  └─ else every MONITOR_INTERVAL (config monitor_interval, default 10m): monitor_positions
        stop / trailing / take-profit only
```

Entry filters (all must pass): volume, hours window, matched bucket, EV, min size, re-fetched ask/spread/slippage, `min_price` / `max_price`, optional Gamma liquidity depth, portfolio risk. Stop = entry − max(entry×stop_loss_pct, min_stop_width).

Portfolio caps (`config.json`): `max_open_positions`, `max_open_per_city`, `max_open_per_date`, `max_capital_at_risk_pct`.

See **`ARCHITECTURE.md`** for the dummy bet and exit matrix.

---

## Coding conventions

- **Match existing style** in `weatherbet/`: plain functions, minimal deps, no type-system rewrite. Put new code in the module that already owns that concern.
- Prefer **small, testable pure functions** for new math/risk logic; keep network at the edges.
- Logs use tags like `[BUY]`, `[SKIP]`, `[RISK]`, `[STOP]`, `[CAL]` — keep that pattern for greppability.
- User-facing docs: complete sentences; no drive-by markdown trees the user did not ask for.
- Do **not** commit:
  - `.env` secrets
  - Large regenerated paper dumps unless the user wants them
  - Unrelated refactors bundled with a behavior change

### When changing behavior

1. Read the relevant section of `ARCHITECTURE.md` + `IMPROVEMENTS.md` (and `MODEL.md` for p/EV/Kelly).
2. Add/adjust **characterization or unit tests first** when possible.
3. Implement the minimal code change in the relevant `weatherbet/` module.
4. Run `pytest`.
5. Note status updates in `IMPROVEMENTS.md` if closing a backlog item; keep `MODEL.md` honest if formulas change.

### When only documenting

Update the smallest set of docs that stay true. Prefer linking over duplicating long math — formulas live in **`MODEL.md`**.

---

## Testing expectations

- Suite is **characterization-first**: assert what the code does *now*, including partition `p`.
- Mark or comment quirks that IMPROVEMENTS still plans to change (horizon σ, bucket shopping).
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

1. ~~Probabilistic partition model~~ **done (matched-bucket only)**; full-event EV shopping still open.
2. Horizon-split calibration; RMSE vs MAE as Gaussian scale (`IMPROVEMENTS` §2).
3. Correlation haircut beyond hard open caps (§3).
4. Source blending, better entry filters, fee-aware paper fills (§4–7).
5. Live trading (§8–9) — explicit go-live criteria exist; do not soft-launch.

---

## Quick “where do I edit?”

| Goal | Start here |
|------|------------|
| Probability / EV / Kelly | `weatherbet/model.py` + **`MODEL.md`** |
| Entry | `weatherbet/entry.py` (`consider_entry`) |
| Scan / resolve | `weatherbet/scan.py` |
| Monitor exits | `weatherbet/monitor.py` |
| Risk caps | `weatherbet/risk.py` + `config.json` |
| Forecast sources | `weatherbet/forecasts.py` |
| Markets / buckets | `weatherbet/polymarket.py` |
| Calibration | `weatherbet/calibration.py` |
| Market files | `weatherbet/storage.py` |
| state.json / KPIs | `weatherbet/state.py` |
| Cities / stations / limits | `weatherbet/config.py` |
| CLI | `weatherbet/cli.py` + `weatherbet.py` launcher |

---

## Definition of done (agent checklist)

- [ ] Behavior matches user request; no silent strategy flips
- [ ] `pytest` green
- [ ] No secrets in commits; config vs `.env` boundary respected
- [ ] Tests updated if characterization surface changed
- [ ] `IMPROVEMENTS.md` / `ARCHITECTURE.md` / `MODEL.md` touched only when they would otherwise lie
- [ ] Real `data/` paper state not clobbered by tests or experiments
