"""
HTML partials for the HTMX dashboard.

Each `partial_*` returns an HTML fragment (not a full document).
Formatting lives here; data math stays in aggregations.py.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

TEMPLATES = Path(__file__).resolve().parent / "templates"


def esc(val: Any) -> str:
    if val is None:
        return ""
    return html.escape(str(val), quote=True)


def fmt_num(n, digits=2) -> str:
    if n is None:
        return "—"
    try:
        return f"{float(n):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_money(n, digits=2) -> str:
    if n is None:
        return "—"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):.{digits}f}"


def pnl_class(n) -> str:
    if n is None:
        return "pnl-zero"
    try:
        v = float(n)
    except (TypeError, ValueError):
        return "pnl-zero"
    if v > 0.005:
        return "pnl-pos"
    if v < -0.005:
        return "pnl-neg"
    return "pnl-zero"


def fmt_ts(iso) -> str:
    if not iso:
        return "—"
    try:
        t = str(iso).replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        return d.strftime("%b %d %H:%M")
    except Exception:
        return esc(str(iso)[:16])


def fmt_ts_short(iso) -> str:
    if not iso:
        return ""
    try:
        t = str(iso).replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        return d.strftime("%b %d")
    except Exception:
        return str(iso)[:10]


def fmt_bucket(t: dict) -> str:
    low = t.get("bucket_low")
    if low is None:
        return "—"
    unit = "°C" if t.get("unit") == "C" else "°F"
    high = t.get("bucket_high")
    if high is None or high == low:
        return f"{low}{unit}"
    return f"{low}–{high}{unit}"


def chart_spec(canvas_id: str, chart_type: str, payload: dict) -> str:
    """Embed chart config for ChartKit.initFromDom after HTMX swap."""
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return (
        f'<script type="application/json" class="chart-spec" '
        f'data-canvas="{esc(canvas_id)}" data-type="{esc(chart_type)}">'
        f"{body}</script>"
    )


def oob_meta(data: dict) -> str:
    """HTMX out-of-band swap for the sticky header subtitle."""
    s = data["summary"]
    meta = (
        f'{s["markets_count"]} markets · {s["actuals_count"]} actuals · '
        f'updated {fmt_ts(s.get("updated_at") or data.get("generated_at"))}'
    )
    return (
        f'<p id="hdr-meta" class="text-[11px] text-slate-500 font-mono" '
        f'hx-swap-oob="true">{esc(meta)}</p>'
    )


def load_template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def render_shell(*, active_tab: str = "overview") -> str:
    tpl = load_template("shell.html")
    return tpl.replace("{{ACTIVE_TAB}}", esc(active_tab))


# ── filters ──────────────────────────────────────────────────

def filter_trades(trades: list[dict], params: dict) -> list[dict]:
    city = (params.get("city") or "").strip()
    status = (params.get("status") or "").strip()
    reason = (params.get("reason") or "").strip()
    source = (params.get("source") or "").strip()
    q = (params.get("q") or "").strip().lower()
    sort = (params.get("sort") or "opened_at").strip()
    reverse = (params.get("dir") or "desc").strip().lower() != "asc"

    rows = list(trades)
    if city:
        rows = [t for t in rows if t.get("city") == city]
    if status:
        rows = [t for t in rows if t.get("position_status") == status]
    if reason:
        rows = [t for t in rows if t.get("close_reason") == reason]
    if source:
        rows = [t for t in rows if t.get("forecast_src") == source]
    if q:
        def match(t):
            blob = " ".join([
                str(t.get("city_name") or ""),
                str(t.get("city") or ""),
                str(t.get("question") or ""),
                str(t.get("date") or ""),
            ]).lower()
            return q in blob
        rows = [t for t in rows if match(t)]

    numeric_keys = {
        "pnl", "ev", "p", "cost", "entry_price", "exit_price", "bucket_low", "kelly",
    }

    def sort_key(t):
        v = t.get(sort)
        if v is None:
            return (1, 0.0, "")
        if sort in numeric_keys or isinstance(v, (int, float)):
            try:
                return (0, float(v), "")
            except (TypeError, ValueError):
                return (1, 0.0, "")
        return (0, 0.0, str(v))

    rows.sort(key=sort_key, reverse=reverse)
    return rows


def _options(values: list[str], selected: str, all_label: str) -> str:
    parts = [f'<option value="">{esc(all_label)}</option>']
    for v in values:
        sel = " selected" if v == selected else ""
        parts.append(f'<option value="{esc(v)}"{sel}>{esc(v)}</option>')
    return "".join(parts)


def _trade_sort_href(params: dict, key: str) -> str:
    p = dict(params)
    cur = p.get("sort") or "opened_at"
    cur_dir = (p.get("dir") or "desc").lower()
    if cur == key:
        p["dir"] = "asc" if cur_dir == "desc" else "desc"
    else:
        p["sort"] = key
        p["dir"] = "desc" if key in ("pnl", "ev", "date", "opened_at", "cost") else "asc"
    p = {k: v for k, v in p.items() if v}
    return "/partials/trades?" + urlencode(p)


# ── partials ─────────────────────────────────────────────────

def partial_overview(data: dict) -> str:
    s = data["summary"]
    series = data["series"]["cumulative_pnl"]
    exits = s.get("exits") or {}

    kpis = [
        ("Balance", fmt_money(s["balance"]), f"start {fmt_money(s['starting_balance'])}", ""),
        ("Equity", fmt_money(s["equity"]), f"open cap {fmt_money(s['open_capital'])}", ""),
        ("Realized PnL", fmt_money(s["realized_pnl"]), f"{fmt_num(s['return_pct'])}% return", pnl_class(s["realized_pnl"])),
        ("Drawdown", f"{fmt_num(s['drawdown_pct'])}%", f"peak {fmt_money(s['peak_balance'])}", "pnl-neg" if (s.get("drawdown_pct") or 0) > 0 else ""),
        ("Trades", f"{s['open_count']} / {s['closed_count']}", f"{s['total_trades']} total · open / closed", ""),
        ("Resolution W/L", f"{s['wins']}–{s['losses']}", "held-to-resolution only", ""),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="kpi-label">{esc(lab)}</div>'
        f'<div class="kpi-value {cls}">{val}</div>'
        f'<div class="kpi-sub">{esc(sub)}</div></div>'
        for lab, val, sub, cls in kpis
    )

    mm = s.get("state_mismatch")
    if mm:
        mismatch = (
            f'<div class="rounded-lg border border-amber-400/40 bg-amber-400/10 px-4 py-3 '
            f'text-sm text-amber-200">State balance ({fmt_money(mm["state_balance"])}) ≠ '
            f'markets ledger ({fmt_money(mm["markets_balance"])}); Δ {fmt_money(mm["delta"])}. '
            f"Markets win — run reconcile if needed.</div>"
        )
    else:
        mismatch = ""

    exit_entries = sorted(exits.items(), key=lambda kv: kv[1]["pnl"])
    exit_rows = "".join(
        f'<tr style="cursor:default"><td>{esc(k)}</td><td>{v["n"]}</td>'
        f'<td class="{pnl_class(v["pnl"])}">{fmt_money(v["pnl"])}</td></tr>'
        for k, v in sorted(exits.items(), key=lambda kv: -kv[1]["pnl"])
    ) or '<tr style="cursor:default"><td colspan="3" class="text-slate-500">No closed trades.</td></tr>'

    bo = s.get("bucket_outcomes") or {}
    hv = s.get("hold_vs_exit") or {}

    cum_spec = chart_spec("chart-cum-pnl", "line-cum", {
        "labels": [fmt_ts_short(p["ts"]) for p in series],
        "values": [p["cum_pnl"] for p in series],
    })
    exit_spec = chart_spec("chart-exits", "bar-signed", {
        "labels": [k for k, _ in exit_entries],
        "values": [v["pnl"] for _, v in exit_entries],
        "label": "PnL",
    })

    return f'''
{oob_meta(data)}
<div class="space-y-6" data-tab="overview">
  <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">{kpi_html}</div>
  {mismatch}

  <div class="grid lg:grid-cols-2 gap-4">
    <div class="card">
      <h2 class="card-title">Cumulative realized PnL</h2>
      <div class="h-64"><canvas id="chart-cum-pnl"></canvas></div>
      {cum_spec}
    </div>
    <div class="card">
      <h2 class="card-title">Exit reasons (PnL)</h2>
      <div class="h-64"><canvas id="chart-exits"></canvas></div>
      {exit_spec}
    </div>
  </div>

  <div class="grid md:grid-cols-3 gap-4">
    <div class="card">
      <h2 class="card-title">Exit mix</h2>
      <div class="overflow-x-auto">
        <table class="data-table">
          <thead><tr><th>Reason</th><th>n</th><th>PnL</th></tr></thead>
          <tbody>{exit_rows}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h2 class="card-title">Bucket outcomes</h2>
      <p class="text-[11px] text-slate-500 mb-2">Polymarket bucket win/loss (includes early exits once annotated). Not the same as stop PnL.</p>
      <div class="grid grid-cols-2 gap-2 text-sm font-mono">
        <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-slate-500 text-[10px] uppercase">Win</div><div class="text-xl pnl-pos">{bo.get("win", 0)}</div></div>
        <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-slate-500 text-[10px] uppercase">Loss</div><div class="text-xl pnl-neg">{bo.get("loss", 0)}</div></div>
        <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-slate-500 text-[10px] uppercase">Pending</div><div class="text-xl text-sky-300">{bo.get("pending", 0)}</div></div>
        <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-slate-500 text-[10px] uppercase">No position</div><div class="text-xl text-slate-400">{bo.get("no_position", 0)}</div></div>
      </div>
    </div>
    <div class="card">
      <h2 class="card-title">Hold vs early exit</h2>
      <p class="text-[11px] text-slate-500 mb-2">Counterfactual: diamond-handing to resolution vs actual exit PnL.</p>
      <div class="space-y-2 font-mono text-sm">
        <div class="flex justify-between"><span class="text-slate-500">Annotated</span><span>{hv.get("annotated", 0)}</span></div>
        <div class="flex justify-between"><span class="text-slate-500">Exit PnL sum</span><span class="{pnl_class(hv.get("exit_pnl_sum"))}">{fmt_money(hv.get("exit_pnl_sum"))}</span></div>
        <div class="flex justify-between"><span class="text-slate-500">Hold PnL sum</span><span class="{pnl_class(hv.get("hold_pnl_sum"))}">{fmt_money(hv.get("hold_pnl_sum"))}</span></div>
        <div class="flex justify-between border-t border-ink-600 pt-2"><span class="text-slate-400">Hold − exit</span><span class="{pnl_class(hv.get("hold_minus_exit"))}">{fmt_money(hv.get("hold_minus_exit"))}</span></div>
      </div>
    </div>
  </div>
</div>
'''


def partial_trades(data: dict, params: dict | None = None) -> str:
    params = dict(params or {})
    trades_all = data["trades"]
    rows = filter_trades(trades_all, params)

    cities = sorted({t["city"] for t in trades_all if t.get("city")})
    reasons = sorted({t["close_reason"] for t in trades_all if t.get("close_reason")})
    sources = sorted({t["forecast_src"] for t in trades_all if t.get("forecast_src")})

    city_opts = _options(cities, params.get("city") or "", "All cities")
    reason_opts = _options(reasons, params.get("reason") or "", "All exits")
    source_opts = _options(sources, params.get("source") or "", "All sources")
    status = params.get("status") or ""
    q = params.get("q") or ""

    def status_opt(val, label):
        sel = " selected" if status == val else ""
        return f'<option value="{esc(val)}"{sel}>{esc(label)}</option>'

    status_opts = (
        status_opt("", "All")
        + status_opt("open", "Open")
        + status_opt("closed", "Closed")
    )

    # hidden sort fields preserved in form
    sort = params.get("sort") or "opened_at"
    direction = params.get("dir") or "desc"

    def th(key, label):
        href = _trade_sort_href(params, key)
        return (
            f'<th hx-get="{esc(href)}" hx-target="#main" hx-swap="innerHTML" '
            f'hx-indicator="#main">{esc(label)}</th>'
        )

    body_rows = []
    for t in rows:
        tid = t.get("id") or ""
        # id is "{city}_{YYYY-MM-DD}" — city may contain hyphens, not underscores
        if "_" in tid:
            city, date = tid.rsplit("_", 1)
        else:
            city, date = tid, ""
        if t.get("position_status") == "open":
            status_badge = '<span class="badge badge-open">open</span>'
        else:
            status_badge = '<span class="badge badge-closed">closed</span>'
        ro = t.get("resolved_outcome")
        if ro == "win":
            ro_html = '<span class="badge badge-win">win</span>'
        elif ro == "loss":
            ro_html = '<span class="badge badge-loss">loss</span>'
        else:
            ro_html = esc(ro) if ro else "—"

        body_rows.append(
            f'''<tr class="trade-row"
                hx-get="/partials/market/{esc(city)}/{esc(date)}"
                hx-target="#drawer-body"
                hx-swap="innerHTML"
                hx-on::after-request="window.Dashboard.openDrawer()">
              <td>{esc(t.get("date"))}</td>
              <td>{esc(t.get("city_name") or t.get("city"))}</td>
              <td>{status_badge}</td>
              <td>{esc(t.get("forecast_src") or "—")}</td>
              <td>{esc(fmt_bucket(t))}</td>
              <td>{fmt_num(t.get("entry_price"), 3)}</td>
              <td>{fmt_num(t.get("exit_price"), 3)}</td>
              <td>{fmt_money(t.get("cost"), 0)}</td>
              <td>{fmt_num(t.get("p"), 3)}</td>
              <td class="{pnl_class(t.get("ev"))}">{fmt_num(t.get("ev"), 2)}</td>
              <td class="{pnl_class(t.get("pnl"))}">{fmt_money(t.get("pnl"))}</td>
              <td>{esc(t.get("close_reason") or "—")}</td>
              <td>{ro_html}</td>
            </tr>'''
        )

    tbody = "\n".join(body_rows) or (
        '<tr style="cursor:default"><td colspan="13" class="text-slate-500">No trades match.</td></tr>'
    )

    return f'''
{oob_meta(data)}
<div class="space-y-4" data-tab="trades">
  <form class="flex flex-wrap gap-2 items-end"
        hx-get="/partials/trades"
        hx-target="#main"
        hx-swap="innerHTML"
        hx-trigger="change, keyup changed delay:300ms from:input[type='search']"
        hx-indicator="#main">
    <input type="hidden" name="sort" value="{esc(sort)}" />
    <input type="hidden" name="dir" value="{esc(direction)}" />
    <label class="filter-label">City
      <select name="city" class="filter-input">{city_opts}</select>
    </label>
    <label class="filter-label">Status
      <select name="status" class="filter-input">{status_opts}</select>
    </label>
    <label class="filter-label">Exit
      <select name="reason" class="filter-input">{reason_opts}</select>
    </label>
    <label class="filter-label">Source
      <select name="source" class="filter-input">{source_opts}</select>
    </label>
    <label class="filter-label grow min-w-[10rem]">Search
      <input name="q" type="search" value="{esc(q)}" placeholder="city, question…" class="filter-input w-full" />
    </label>
    <span class="text-xs text-slate-500 pb-2">{len(rows)} trades</span>
  </form>

  <div class="card p-0 overflow-hidden">
    <div class="overflow-x-auto max-h-[70vh]">
      <table class="data-table">
        <thead>
          <tr>
            {th("date", "Date")}
            {th("city_name", "City")}
            {th("position_status", "Status")}
            {th("forecast_src", "Src")}
            {th("bucket_low", "Bucket")}
            {th("entry_price", "Entry")}
            {th("exit_price", "Exit")}
            {th("cost", "Cost")}
            {th("p", "p")}
            {th("ev", "EV")}
            {th("pnl", "PnL")}
            {th("close_reason", "Reason")}
            {th("resolved_outcome", "Bucket")}
          </tr>
        </thead>
        <tbody>{tbody}</tbody>
      </table>
    </div>
  </div>
</div>
'''


def partial_cities(data: dict) -> str:
    cities = sorted(data["cities"], key=lambda c: c["realized_pnl"])
    chart = chart_spec("chart-city-pnl", "bar-signed", {
        "labels": [c.get("city_name") or c["city"] for c in cities],
        "values": [c["realized_pnl"] for c in cities],
        "label": "PnL",
        "horizontal": True,
    })

    rows = []
    for c in sorted(data["cities"], key=lambda x: x.get("city_name") or x["city"]):
        exits = " ".join(f"{k}:{n}" for k, n in (c.get("exits") or {}).items())
        rows.append(
            f'''<tr hx-get="/partials/trades?city={esc(c["city"])}"
                    hx-target="#main" hx-swap="innerHTML"
                    hx-on::after-request="window.Dashboard.setActiveTab('trades')">
              <td>{esc(c.get("city_name") or c["city"])}</td>
              <td>{esc(c.get("unit") or "—")}</td>
              <td>{c["markets"]}</td>
              <td>{c["trades"]}</td>
              <td>{c["open"]}</td>
              <td>{c["closed"]}</td>
              <td class="{pnl_class(c["realized_pnl"])}">{fmt_money(c["realized_pnl"])}</td>
              <td class="{pnl_class(c.get("avg_pnl"))}">{fmt_money(c.get("avg_pnl"))}</td>
              <td>{c.get("bucket_win", 0)}/{c.get("bucket_loss", 0)}</td>
              <td>{fmt_num(c.get("best_mae"), 2)}</td>
              <td class="text-[10px] text-slate-400 max-w-[12rem] truncate" title="{esc(exits)}">{esc(exits) or "—"}</td>
            </tr>'''
        )

    return f'''
{oob_meta(data)}
<div class="space-y-4" data-tab="cities">
  <div class="card">
    <h2 class="card-title">PnL by city</h2>
    <div class="h-80"><canvas id="chart-city-pnl"></canvas></div>
    {chart}
  </div>
  <div class="card p-0 overflow-hidden">
    <div class="overflow-x-auto">
      <table class="data-table">
        <thead>
          <tr>
            <th>City</th><th>Unit</th><th>Markets</th><th>Trades</th>
            <th>Open</th><th>Closed</th><th>Realized PnL</th><th>Avg PnL</th>
            <th>Bucket W/L</th><th>Best MAE</th><th>Exits</th>
          </tr>
        </thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
  </div>
</div>
'''


def partial_sources(data: dict) -> str:
    trade_pnl = data["sources"]["trade_pnl"]
    accuracy = data["sources"]["accuracy"]
    cal = data["sources"]["calibration"]

    pnl_chart = chart_spec("chart-src-pnl", "bar-signed", {
        "labels": [r["source"] for r in trade_pnl],
        "values": [r["pnl"] for r in trade_pnl],
        "label": "PnL",
    })

    pnl_rows = "".join(
        f'''<tr style="cursor:default">
          <td>{esc(r["source"])}</td><td>{r["n"]}</td>
          <td class="{pnl_class(r["pnl"])}">{fmt_money(r["pnl"])}</td>
          <td class="{pnl_class(r.get("avg_pnl"))}">{fmt_money(r.get("avg_pnl"))}</td>
          <td class="{pnl_class(r.get("median_pnl"))}">{fmt_money(r.get("median_pnl"))}</td>
          <td class="text-[10px] text-slate-400">{esc(" ".join(f"{k}:{n}" for k, n in (r.get("exits") or {}).items()))}</td>
        </tr>'''
        for r in trade_pnl
    ) or '<tr style="cursor:default"><td colspan="6" class="text-slate-500">No closed trades.</td></tr>'

    last_snap = accuracy.get("last_snap") or {}
    mae_rows_data = []
    for unit, srcs in last_snap.items():
        for src, st in srcs.items():
            if st.get("n") and st.get("mae") is not None:
                mae_rows_data.append({
                    "src": src, "unit": unit, "n": st["n"],
                    "mae": st["mae"], "bias": st.get("bias"), "rmse": st.get("rmse"),
                })
    mae_rows_data.sort(key=lambda r: r["mae"])

    mae_chart = chart_spec("chart-src-mae", "bar-signed", {
        "labels": [f'{r["src"]} (°{r["unit"]})' for r in mae_rows_data],
        "values": [r["mae"] for r in mae_rows_data],
        "label": "MAE",
    })

    mae_table = "".join(
        f'''<tr style="cursor:default">
          <td>{esc(r["src"])}</td><td>°{esc(r["unit"])}</td><td>{r["n"]}</td>
          <td>{fmt_num(r["mae"], 3)}</td>
          <td>{fmt_num(r["bias"], 3)}</td>
          <td>{fmt_num(r["rmse"], 3)}</td>
        </tr>'''
        for r in mae_rows_data
    ) or '<tr style="cursor:default"><td colspan="6" class="text-slate-500">No actuals yet.</td></tr>'

    at_entry = accuracy.get("at_entry") or {}
    entry_parts = []
    for unit, srcs in at_entry.items():
        entry_parts.append(f'<h3 class="text-xs text-slate-400 mb-1 mt-2">Unit °{esc(unit)}</h3>')
        entry_parts.append(
            '<table class="data-table"><thead><tr><th>Source</th><th>n</th>'
            '<th>MAE</th><th>Bias</th><th>RMSE</th></tr></thead><tbody>'
        )
        for src, st in sorted(srcs.items(), key=lambda kv: (kv[1].get("mae") is None, kv[1].get("mae") or 99)):
            entry_parts.append(
                f'<tr style="cursor:default"><td>{esc(src)}</td><td>{st["n"]}</td>'
                f'<td>{fmt_num(st.get("mae"), 3)}</td>'
                f'<td>{fmt_num(st.get("bias"), 3)}</td>'
                f'<td>{fmt_num(st.get("rmse"), 3)}</td></tr>'
            )
        entry_parts.append("</tbody></table>")
    entry_html = "".join(entry_parts) or '<p class="text-slate-500 text-sm">No entry residuals.</p>'

    spread = accuracy.get("hrrr_ecmwf_spread")
    if spread:
        spread_html = f'''
        <div class="grid grid-cols-2 gap-2 font-mono text-sm">
          <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-[10px] text-slate-500 uppercase">n snaps</div><div class="text-lg">{spread["n"]}</div></div>
          <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-[10px] text-slate-500 uppercase">mean |Δ|</div><div class="text-lg">{fmt_num(spread["mean"], 2)}</div></div>
          <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-[10px] text-slate-500 uppercase">p50</div><div class="text-lg">{fmt_num(spread["p50"], 2)}</div></div>
          <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-[10px] text-slate-500 uppercase">p90</div><div class="text-lg">{fmt_num(spread["p90"], 2)}</div></div>
          <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-[10px] text-slate-500 uppercase">p95</div><div class="text-lg">{fmt_num(spread["p95"], 2)}</div></div>
          <div class="rounded-lg bg-ink-800/80 p-3"><div class="text-[10px] text-slate-500 uppercase">max</div><div class="text-lg">{fmt_num(spread["max"], 2)}</div></div>
        </div>'''
    else:
        spread_html = '<p class="text-slate-500 text-sm">No dual HRRR+ECMWF snaps yet.</p>'

    if cal:
        cal_html = (
            '<table class="data-table"><thead><tr><th>Key</th><th>σ</th><th>Bias</th><th>n</th></tr></thead><tbody>'
            + "".join(
                f'<tr style="cursor:default"><td>{esc(r["key"])}</td>'
                f'<td>{fmt_num(r.get("sigma"), 3)}</td>'
                f'<td>{fmt_num(r.get("bias"), 3)}</td>'
                f'<td>{esc(r.get("n") if r.get("n") is not None else "—")}</td></tr>'
                for r in cal
            )
            + "</tbody></table>"
        )
    else:
        cal_html = (
            '<p class="text-slate-500 text-sm">calibration.json is empty — '
            "defaults still drive σ/bias at entry.</p>"
        )

    return f'''
{oob_meta(data)}
<div class="space-y-4" data-tab="sources">
  <div class="grid lg:grid-cols-2 gap-4">
    <div class="card">
      <h2 class="card-title">Trade PnL by entry source</h2>
      <p class="text-[11px] text-slate-500 mb-2">Closed positions grouped by <code class="text-slate-400">forecast_src</code> at entry.</p>
      <div class="h-64"><canvas id="chart-src-pnl"></canvas></div>
      {pnl_chart}
      <div class="mt-3 overflow-x-auto">
        <table class="data-table">
          <thead><tr><th>Source</th><th>n</th><th>PnL</th><th>Avg</th><th>Median</th><th>Exits</th></tr></thead>
          <tbody>{pnl_rows}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h2 class="card-title">Forecast MAE (last snap vs actual)</h2>
      <p class="text-[11px] text-slate-500 mb-2">Residuals split by unit (°F / °C). Thin n = noisy ranks.</p>
      <div class="h-64"><canvas id="chart-src-mae"></canvas></div>
      {mae_chart}
      <div class="mt-3 overflow-x-auto">
        <table class="data-table">
          <thead><tr><th>Source</th><th>Unit</th><th>n</th><th>MAE</th><th>Bias</th><th>RMSE</th></tr></thead>
          <tbody>{mae_table}</tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="grid md:grid-cols-2 gap-4">
    <div class="card">
      <h2 class="card-title">HRRR ↔ ECMWF spread</h2>
      <p class="text-[11px] text-slate-500 mb-2">|hrrr − ecmwf| across snaps where both present.</p>
      {spread_html}
    </div>
    <div class="card">
      <h2 class="card-title">Calibration file</h2>
      {cal_html}
    </div>
  </div>

  <div class="card">
    <h2 class="card-title">Accuracy at entry snap (vs actual)</h2>
    <div class="overflow-x-auto">{entry_html}</div>
  </div>
</div>
'''


SRC_COLORS = [
    "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#a78bfa",
    "#f472b6", "#2dd4bf", "#94a3b8", "#eab308", "#60a5fa",
]


def partial_market(detail: dict) -> str:
    m = detail
    pos = m.get("position")
    unit = "°C" if m.get("unit") == "C" else "°F"

    if pos:
        pos_html = f'''
        <div class="grid grid-cols-2 gap-2 font-mono text-xs">
          <div><span class="text-slate-500">Status</span><div>{esc(pos.get("status"))}</div></div>
          <div><span class="text-slate-500">Source</span><div>{esc(pos.get("forecast_src") or "—")}</div></div>
          <div><span class="text-slate-500">Entry</span><div>{fmt_num(pos.get("entry_price"), 3)}</div></div>
          <div><span class="text-slate-500">Exit</span><div>{fmt_num(pos.get("exit_price"), 3)}</div></div>
          <div><span class="text-slate-500">Cost</span><div>{fmt_money(pos.get("cost"))}</div></div>
          <div><span class="text-slate-500">PnL</span><div class="{pnl_class(pos.get("pnl"))}">{fmt_money(pos.get("pnl"))}</div></div>
          <div><span class="text-slate-500">p / EV</span><div>{fmt_num(pos.get("p"), 3)} / {fmt_num(pos.get("ev"), 2)}</div></div>
          <div><span class="text-slate-500">Reason</span><div>{esc(pos.get("close_reason") or "—")}</div></div>
          <div class="col-span-2"><span class="text-slate-500">Question</span>
            <div class="text-slate-300 font-sans text-sm mt-0.5">{esc(pos.get("question") or "—")}</div></div>
        </div>'''
    else:
        pos_html = '<p class="text-slate-500">No position on this market.</p>'

    fs = m.get("forecast_series") or {}
    labels = [fmt_ts_short(t) for t in (fs.get("ts") or [])]
    series = []
    if fs.get("best") and any(v is not None for v in fs["best"]):
        series.append({"label": "best", "data": fs["best"], "color": "#fff"})
    for i, k in enumerate(m.get("source_keys") or []):
        series.append({
            "label": k,
            "data": (fs.get("sources") or {}).get(k) or [],
            "color": SRC_COLORS[i % len(SRC_COLORS)],
        })
    fc_spec = chart_spec("chart-drawer-fc", "multi-line", {
        "labels": labels,
        "series": series,
        "actual": m.get("actual_temp"),
    })

    ps = m.get("price_series") or {}
    px_spec = chart_spec("chart-drawer-px", "line-cum", {
        "labels": [fmt_ts_short(t) for t in (ps.get("ts") or [])],
        "values": ps.get("top_price") or [],
        "label": "top price",
    })

    actual = m.get("actual_temp")
    actual_s = f"{actual}{unit}" if actual is not None else "—"

    title = f'{m.get("city_name") or m.get("city")} · {m.get("date")}'

    return f'''
<h2 id="drawer-title" class="font-semibold text-white text-sm sm:text-base" hx-swap-oob="true">{esc(title)}</h2>
<div class="space-y-4 text-sm">
  <div class="grid grid-cols-2 gap-2 text-xs font-mono">
    <div><span class="text-slate-500">Station</span><div>{esc(m.get("station") or "—")}</div></div>
    <div><span class="text-slate-500">Status</span><div>{esc(m.get("status") or "—")}</div></div>
    <div><span class="text-slate-500">Actual</span><div class="text-amber-300">{esc(actual_s)}</div></div>
    <div><span class="text-slate-500">Bucket outcome</span><div>{esc(m.get("resolved_outcome") or "—")}</div></div>
    <div><span class="text-slate-500">Hold-to-res PnL</span><div class="{pnl_class(m.get("hold_to_resolution_pnl"))}">{fmt_money(m.get("hold_to_resolution_pnl"))}</div></div>
    <div><span class="text-slate-500">Held to res?</span><div>{esc(m.get("held_to_resolution") if m.get("held_to_resolution") is not None else "—")}</div></div>
  </div>
  <div class="card" style="background:rgba(18,26,43,0.5)">
    <h3 class="card-title">Position</h3>
    {pos_html}
  </div>
  <div class="card" style="background:rgba(18,26,43,0.5)">
    <h3 class="card-title">Forecasts over time</h3>
    <div class="h-56"><canvas id="chart-drawer-fc"></canvas></div>
    {fc_spec}
  </div>
  <div class="card" style="background:rgba(18,26,43,0.5)">
    <h3 class="card-title">Top bucket price</h3>
    <div class="h-40"><canvas id="chart-drawer-px"></canvas></div>
    {px_spec}
  </div>
</div>
'''


def partial_error(message: str, status_hint: str = "") -> str:
    return (
        f'<div class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 '
        f'text-sm text-rose-300">{esc(message)}'
        f'{(" · " + esc(status_hint)) if status_hint else ""}</div>'
    )
