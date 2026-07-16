# WeatherBet — Characterization Test Plan

**Goal:** Lock **current** behavior with automated tests so later IMPROVEMENTS are deliberate diffs, not silent drift.

**Scope:** Baseline / characterization only. Do **not** change trading logic to “match better math” while writing these tests. Document what the code does today — including binary `p` and dead calibration paths.

**Out of scope (later):** portfolio caps, probabilistic `bucket_prob`, live SDK, rewriting architecture for purity (only extract if testing is otherwise painful).

**Last updated:** 2026-07-16

---

## 1. Principles

1. **Characterization over aspiration** — assert today’s return values even when IMPROVEMENTS.md calls them wrong.
2. **Pure functions first** — no network in unit tests.
3. **Mark known quirks** — comments or `@pytest.mark.characterization` so future changes update tests intentionally.
4. **Remote paper data is optional Phase 3** — nice for integration fixtures; not required to start.
5. **One green suite before any IMPROVEMENTS PR.**

---

## 2. Current constraints (affect how we test)

| Issue | Impact on tests |
|--------|------------------|
| `weatherbet.py` loads `config.json` + creates `data/` at import | Need repo-root cwd, a real/minimal `config.json`, or a small import shim |
| Config constants (`MAX_BET`, `KELLY_FRACTION`, …) bound at import | `bet_size` / Kelly tests depend on `config.json` values — pin them or patch module attrs |
| I/O uses `DATA_DIR` / `MARKETS_DIR` / `STATE_FILE` | Use `tmp_path` + monkeypatch paths for storage tests |
| Network helpers (`get_ecmwf`, Gamma, VC) | Mock `requests` only; never hit live APIs in CI |
| `scan_and_update` / `run_loop` are large | Defer full scan tests; prefer pure math + small extracted decision helpers later |

---

## 3. Tooling setup (Phase 0)

**Deliverables:**

```text
requirements-dev.txt   # pytest, (optional) pytest-cov
tests/
  conftest.py
  test_norm_cdf.py
  test_parse_temp_range.py
  test_in_bucket.py
  test_bucket_prob.py
  test_ev_kelly_sizing.py
  test_hours_to_resolution.py
  test_calibration.py
  test_market_storage.py
  test_cli.py            # optional, light
pytest.ini or pyproject.toml [tool.pytest.ini_options]
```

**Tasks:**

1. Add `pytest` (and optional `pytest-cov`).
2. `conftest.py`: ensure imports work from repo root; document that tests run with `config.json` present.
3. README section: `pip install -r requirements-dev.txt && pytest`.
4. Convention: tests that pin “arguably wrong but current” behavior include a short comment referencing IMPROVEMENTS §1 if useful.

**Success criteria:** `pytest` collects and runs with 0 failures on a clean checkout (with `config.json`).

---

## 4. Function inventory and priority

### P0 — must baseline (math + parsing)

| Function | File area | Test focus |
|----------|-----------|------------|
| `norm_cdf` | math | Monotone; `norm_cdf(0)≈0.5`; symmetric tails |
| `parse_temp_range` | polymarket | `or below`, `or higher`, `between A-B`, `be N°F/C on` → ranges; garbage → `None` |
| `in_bucket` | polymarket | Range inclusive; zero-width uses `round(forecast)==round(t_low)` |
| `bucket_prob` | math | Binary middle; CDF edges; **zero-width with match → 1.0** (not continuous 0) |
| `calc_ev` | math | Formula; price 0/1 → 0; `p=1` cheap ask → large positive EV |
| `calc_kelly` | math | `p=1` → fraction of bankroll path; clamps; bad prices → 0 |
| `bet_size` | math | Cap at `MAX_BET`; scales with balance × kelly |

### P1 — important (calibration + storage contracts)

| Function | Test focus |
|----------|------------|
| `get_sigma` | Default `SIGMA_F` / `SIGMA_C` by unit; override from loaded `_cal` |
| `load_cal` / `run_calibration` | Empty input; below `CALIBRATION_MIN` → no update; enough fakes with `actual_temp` → sigma keys; **document if status field mismatch leaves cal empty** |
| `market_path`, `new_market`, `save_market`, `load_market`, `load_all_markets` | Round-trip JSON under `tmp_path` |
| `load_state` / `save_state` | Defaults when missing; round-trip |
| `hours_to_resolution` | Fixed freezegame or fixed “now” via patching `datetime` if needed; invalid → 999 |

### P2 — mock network only (optional in first PR)

| Function | Test focus |
|----------|------------|
| `check_market_resolved` | Mock Gamma JSON: open → `None`; yes≈1 → `True`; no≈0 → `False` |
| `get_polymarket_event` | Mock list with event / empty |
| `get_market_price` | Mock `outcomePrices` |
| `get_actual_temp` | Mock VC response; missing key/error → `None` |

**Explicitly not required for baseline PR:** full `scan_and_update`, `monitor_positions`, `run_loop`, `print_status`, `print_report` (smoke/CLI only if cheap).

---

## 5. Detailed cases (P0)

### 5.1 `parse_temp_range`

| Input (question fragment) | Expected |
|---------------------------|----------|
| `... 50°F or below ...` | `(-999.0, 50.0)` |
| `... 90°F or higher ...` | `(90.0, 999.0)` |
| `... between 46-47°F ...` | `(46.0, 47.0)` |
| `... be 80°F on ...` | `(80.0, 80.0)`  ← zero-width |
| `... be 26°C on ...` | `(26.0, 26.0)` |
| `""` / unrelated text | `None` |

Match real Polymarket-ish wording where possible (full question strings optional).

### 5.2 `in_bucket`

| forecast | low | high | expected |
|----------|-----|------|----------|
| 80 | 80 | 80 | True |
| 80.4 | 80 | 80 | True (rounds) |
| 80.6 | 80 | 80 | False if round→81 |
| 81 | 80 | 80 | False |
| 46.5 | 46 | 47 | True |
| 45 | 46 | 47 | False |

### 5.3 `bucket_prob` (characterization — current semantics)

| Case | expected behavior |
|------|-------------------|
| Middle bin, forecast inside | `1.0` **regardless of sigma** |
| Middle bin, forecast outside | `0.0` |
| Zero-width, rounded match | `1.0` (not 0.0 — documents Trap A avoidance) |
| Zero-width, no match | `0.0` |
| `t_low == -999` | CDF: `Φ((t_high - f) / s)` |
| `t_high == 999` | `1 - Φ((t_low - f) / s)` |
| Default sigma when `None` | uses `2.0` on edges |

Optional explicit non-goal comment in test file:

> Continuous equal-bound CDF is **not** current behavior; do not “fix” these tests to that without a product decision.

### 5.4 EV / Kelly / size (with current config defaults)

Assume `config.json`: `kelly_fraction=0.25`, `max_bet=20` (assert or skip if config differs).

| Case | Check |
|------|--------|
| `calc_ev(1.0, 0.35)` | `≈ 1/0.35 - 1` (huge positive) — why max bets look good |
| `calc_ev(0.197, 0.35)` | negative — documents Trap B *if* continuous were used (reference only; not current `bucket_prob`) |
| `calc_ev(0.5, 0)` / `1` | `0.0` |
| `calc_kelly(1.0, 0.35)` | positive, capped by kelly_fraction path |
| `bet_size(1.0, 10000)` | `== MAX_BET` (20) |
| `bet_size(0.001, 100)` | small size or min logic as implemented |

### 5.5 Edge CDF smoke

- Forecast far below “or higher” floor → high `p`
- Forecast far above “or below” cap → high `p`
- Values in `[0, 1]`

---

## 6. Detailed cases (P1)

### 6.1 Calibration

Build fake market dicts in memory (no API):

```text
{
  "city": "nyc",
  "resolved": ...,   # use whatever run_calibration actually checks
  "status": "resolved",
  "actual_temp": 80,
  "forecast_snapshots": [{"source": "ecmwf", "temp": 82}, ...]
}
```

**Pin observed behavior:**

1. If code requires a field that production resolve never sets → test documents “calibration never updates” (characterization of the bug).
2. If enough valid errors → `calibration.json` under temp dir gets `nyc_ecmwf` (or whatever key format) with `sigma` ≈ MAE.

Monkeypatch `CALIBRATION_FILE`, `CALIBRATION_MIN` as needed.

### 6.2 Storage

- `new_market` has expected keys (`position` None, empty snapshots, etc.).
- save → load equality (JSON round-trip).
- `load_all_markets` ignores bad JSON files or skips errors as implemented.

### 6.3 `get_sigma`

- US city, empty cal → `SIGMA_F` (2.0).
- °C city → `SIGMA_C` (1.2).
- Inject `_cal[city_source]` → returns that sigma.

---

## 7. Import / config strategy

**Preferred (minimal change):**

- Run pytest from repo root.
- Keep committed `config.json` as the pin for defaults used in sizing tests.
- In tests that need isolation, `monkeypatch.setattr(weatherbet, "MAX_BET", 20.0)` etc.

**If import side effects become painful (only then):**

- Tiny refactor PR: lazy-load config or `load_config(path)` — still behavior-preserving, covered by same tests.

Avoid large restructure in the testing phase.

---

## 8. Phase plan

### Phase 0 — Harness (½ day)

- [x] `requirements-dev.txt` + pytest config
- [x] `tests/conftest.py`
- [x] README: how to run tests
- [x] One trivial test proves import works

### Phase 1 — P0 unit tests (1 day)

- [x] `norm_cdf`, `parse_temp_range`, `in_bucket`
- [x] `bucket_prob` characterization matrix (incl. zero-width)
- [x] `calc_ev`, `calc_kelly`, `bet_size`
- [x] All green

### Phase 2 — P1 unit tests (½–1 day)

- [x] sigma + calibration with tmp files / fake markets
- [x] market/state storage round-trips
- [x] `hours_to_resolution` (with time patch if needed)
- [x] All green

### Phase 3 — Optional P2 mocks + fixtures (as needed)

- [ ] Mocked resolve / price / VC helpers
- [ ] Optional: anonymized samples from remote `data/markets/*.json` as **read-only fixtures** under `tests/fixtures/` (no secrets)
- [ ] Offline script or test: recompute “shadow” continuous `p` on fixture entries **without** changing production code (comparison aid, not characterization of current `bucket_prob`)

### Phase 4 — Gate

- [ ] `pytest` in local workflow before any IMPROVEMENTS implementation
- [ ] Optional: CI later (GitHub Actions) — not required for baseline

**Exit criteria for “baseline done”:** Phases 0–2 green; P0 cases in §5 all covered; calibration/storage contracts pinned.

---

## 9. How tests interact with IMPROVEMENTS later

| When you change… | Test action |
|------------------|-------------|
| Portfolio caps | Add new tests; leave binary `bucket_prob` tests as-is |
| Wire `actual_temp` on resolve | Update calibration tests from “dead” → “updates”; keep old fixture if useful as regression on field names |
| New discrete `bucket_prob` | **New** tests (or new function); update old characterization tests in the **same PR** with explicit “behavior change” notes |
| Match-style honesty (drop fake Kelly) | Replace EV/Kelly entry tests with new sizing policy tests |

Never “quietly” edit characterization tests to green continuous-σ=2 without calling it a product change.

---

## 10. What not to do in this testing effort

- Hit live Open-Meteo / Polymarket / Visual Crossing in unit tests
- Rewrite `scan_and_update` only to make it testable (extract later if needed)
- Change `bucket_prob` while writing baseline
- Aim for 100% line coverage of print loops
- Commit real `VC_KEY` or full production `data/` with anything sensitive (fixtures only)

---

## 11. Suggested first PR (slice)

**Title:** `test: characterization suite for math and parsing`

**Includes:** Phase 0 + Phase 1 only.

**Does not include:** calibration deep dives, network mocks, IMPROVEMENTS.

**Review checklist:**

- [ ] Zero-width → `p=1` when in bucket (documents current design)
- [ ] Middle bin ignores sigma
- [ ] `p=1` + typical ask → large EV / max bet path with current config
- [ ] No network

---

## 12. Success definition

You can say the baseline is done when:

1. `pytest` is one command and green on main.
2. A stranger can read `test_bucket_prob.py` and learn that middle buckets are binary and zero-width is not continuous CDF.
3. Changing `bucket_prob` or Kelly math **fails CI/local tests** until tests are updated on purpose.
4. IMPROVEMENTS work can start without fear of silent regression on parse/math/storage.

---

## 13. Immediate next action

Implement **Phase 0 + Phase 1** (harness + P0 tests). Stop and confirm green before Phase 2 or any IMPROVEMENTS code.
