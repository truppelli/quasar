"""QUASAR visualizer: python serve.py, then open http://localhost:8000

GET /                         the map page (viz.html)
GET /resorts                  resort names in resorts/
GET /resort?resort=toy        nodes and edges for drawing
GET /plan?resort=toy&start=summit&minutes=25[&end=base]   optimal route JSON (quasar.plan)
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import quasar

ROOT = Path(__file__).parent
RESORTS = ROOT / "resorts"
MAX_MINUTES = 240  # ponytail: search is exponential in the budget; cap until large resorts get pod decomposition


def resort_names():
    return sorted(p.stem for p in RESORTS.glob("*.json"))


def api(path, q):
    """Returns (status, body). Query values are untrusted: resort must be a known file, start/end real nodes."""
    if path == "/resorts":
        return 200, resort_names()
    name = q.get("resort", "")
    if name not in resort_names():
        return 400, {"error": f"unknown resort {name!r}"}
    r = quasar.load(RESORTS / f"{name}.json")
    if path == "/resort":
        return 200, {k: r[k] for k in ("name", "base", "nodes", "edges")}
    if path == "/plan":
        start, end = q.get("start", r["base"]), q.get("end", r["base"])
        if start not in r["nodes"] or end not in r["nodes"]:
            return 400, {"error": "unknown start/end node"}
        try:
            minutes = float(q.get("minutes", ""))
        except ValueError:
            return 400, {"error": "minutes must be a number"}
        if not 0 <= minutes <= MAX_MINUTES:
            return 400, {"error": f"minutes must be 0-{MAX_MINUTES}"}
        return 200, quasar.plan(r, start, minutes, end) or {"error": f"can't reach {end} in {minutes:g} min"}
    return 404, {"error": "not found"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            status, body, ctype = 200, (ROOT / "viz.html").read_bytes(), "text/html; charset=utf-8"
        else:
            status, data = api(url.path, {k: v[0] for k, v in parse_qs(url.query).items()})
            body, ctype = json.dumps(data).encode(), "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    assert api("/plan", {"resort": "toy", "start": "summit", "minutes": "25"})[1]["vertical_m"] == 1400
    assert api("/plan", {"resort": "../quasar", "minutes": "25"})[0] == 400
    assert api("/plan", {"resort": "toy", "start": "nowhere", "minutes": "25"})[0] == 400
    assert api("/plan", {"resort": "toy", "minutes": "1e9"})[0] == 400
    print("QUASAR visualizer on http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
