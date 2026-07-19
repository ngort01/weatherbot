# WeatherBet paper dashboard

Read-only local UI over `data/` — bankroll, trades, per-city stats, forecast source quality.

## Run

```bash
python3 dashboard/server.py
# → http://127.0.0.1:8765
```

```bash
python3 dashboard/server.py --port 8765 --data /path/to/data --host 127.0.0.1
```

No npm/build. Tailwind + Chart.js + **HTMX** from CDN.

## Architecture

```text
dashboard/
  server.py           # routes: shell, /partials/*, /api/*, static
  aggregations.py     # pure data → stats (no HTML)
  render.py           # stats → HTML fragments
  templates/shell.html
  static/css|js       # chrome + ChartKit only
```

| Layer | Role |
|-------|------|
| `aggregations.py` | Load `data/`, compute KPIs / tables / series |
| `render.py` | HTML partials + formatting |
| HTMX | Tab swaps, trade filters, market drawer |
| `charts.js` | Reads embedded `<script class="chart-spec">` after each swap |

### Routes

| Path | Response |
|------|----------|
| `GET /?tab=overview` | Full shell; `#main` loads partial on `hx-trigger=load` |
| `GET /partials/overview` | Overview HTML |
| `GET /partials/trades?city=&status=&…` | Filterable trades table |
| `GET /partials/cities` | City stats |
| `GET /partials/sources` | Forecast source comparison |
| `GET /partials/market/{city}/{date}` | Drawer body |
| `GET /api/dashboard` | JSON (debug / optional) |

## Data

| Path | Use |
|------|-----|
| `data/state.json` | Ledger KPIs (cross-checked vs markets) |
| `data/markets/*.json` | Ground-truth trades, snaps, actuals |
| `data/calibration.json` | σ / bias when populated |

Read-only. No writes, no live APIs, no bot package import.
