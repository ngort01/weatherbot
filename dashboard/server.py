#!/usr/bin/env python3
"""
Local read-only dashboard for WeatherBet paper data.

  python3 dashboard/server.py
  python3 dashboard/server.py --port 8765 --data data

Shell page + HTMX HTML partials over data/. Optional JSON for debugging.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from aggregations import build_dashboard, market_detail
from render import (
    partial_cities,
    partial_error,
    partial_market,
    partial_overview,
    partial_sources,
    partial_trades,
    render_shell,
)

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DEFAULT_DATA = ROOT.parent / "data"
DEFAULT_PORT = 8765

TABS = frozenset({"overview", "trades", "cities", "sources"})


class DashboardHandler(SimpleHTTPRequestHandler):
    data_dir: Path = DEFAULT_DATA

    def __init__(self, *args, data_dir: Path = DEFAULT_DATA, **kwargs):
        self.data_dir = Path(data_dir)
        # directory= only matters for fallback; we handle routes ourselves
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        # flatten single-value query params
        params = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}

        # ── shell (never serve static/index.html — templates/shell.html only)
        if path in ("/", "", "/index.html", "/index.htm"):
            tab = params.get("tab", "overview")
            if tab not in TABS:
                tab = "overview"
            return self._html(render_shell(active_tab=tab))

        # ── HTMX partials ────────────────────────────────────
        if path.startswith("/partials/"):
            return self._handle_partial(path, params)

        # ── JSON (debug / optional clients) ──────────────────
        if path in ("/api/dashboard", "/api/dashboard/"):
            return self._json(build_dashboard(self.data_dir))

        m = re.fullmatch(r"/api/market/([^/]+)/([^/]+)/?", path)
        if m:
            detail = market_detail(self.data_dir, m.group(1), m.group(2))
            if detail is None:
                return self._json({"error": "not found"}, status=404)
            return self._json(detail)

        # ── static ───────────────────────────────────────────
        rel = path.lstrip("/")
        candidate = (STATIC / rel).resolve()
        if not str(candidate).startswith(str(STATIC.resolve())):
            return self._html(partial_error("forbidden"), status=403)
        if candidate.is_file():
            ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            if candidate.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif candidate.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            return self._send_file(candidate, ctype)

        return self._html(partial_error("not found"), status=404)

    def _handle_partial(self, path: str, params: dict):
        try:
            data = build_dashboard(self.data_dir)
        except Exception as e:
            return self._html(partial_error(f"Failed to load data: {e}"), status=500)

        if path in ("/partials/overview", "/partials/overview/"):
            body = partial_overview(data)
            return self._html(body, tab="overview")

        if path in ("/partials/trades", "/partials/trades/"):
            body = partial_trades(data, params)
            return self._html(body, tab="trades")

        if path in ("/partials/cities", "/partials/cities/"):
            body = partial_cities(data)
            return self._html(body, tab="cities")

        if path in ("/partials/sources", "/partials/sources/"):
            body = partial_sources(data)
            return self._html(body, tab="sources")

        m = re.fullmatch(r"/partials/market/([^/]+)/([^/]+)/?", path)
        if m:
            detail = market_detail(self.data_dir, m.group(1), m.group(2))
            if detail is None:
                return self._html(partial_error("market not found"), status=404)
            return self._html(partial_market(detail))

        return self._html(partial_error("unknown partial"), status=404)

    def _html(self, body: str, status=200, tab: str | None = None):
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if tab:
            # Client uses this to highlight the active tab + refresh target
            self.send_header("HX-Trigger", json.dumps({"wb:tab": tab}))
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except OSError:
            return self._html(partial_error("not found"), status=404)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description="WeatherBet paper dashboard")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="Path to data/ directory (default: repo data/)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    data_dir = args.data.resolve()
    if not data_dir.is_dir():
        print(f"warning: data dir does not exist: {data_dir}", file=sys.stderr)

    handler = partial(DashboardHandler, data_dir=data_dir)
    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as e:
        if getattr(e, "errno", None) == 98:  # EADDRINUSE
            print(
                f"error: {args.host}:{args.port} already in use.\n"
                f"  free it:  fuser -k {args.port}/tcp\n"
                f"  or use:   python3 dashboard/server.py --port {args.port + 1}",
                file=sys.stderr,
            )
            return 1
        raise
    print(f"WeatherBet dashboard  http://{args.host}:{args.port}")
    print(f"  data → {data_dir}")
    print("  Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.server_close()
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
