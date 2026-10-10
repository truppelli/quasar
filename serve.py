"""QUASAR visualizer: python serve.py [port], then open http://localhost:8000 (or your port)

GET /                         the map page (viz.html)
GET /resorts                  resort names in resorts/
GET /resort?resort=toy        nodes, edges and origin_lonlat (node x/y are metres from it)
GET /plan?resort=toy&start=summit&minutes=25[&end=base]   best route JSON (quasar.plan)
GET /3d                       the 3D mountain map (map3d.html)
GET /geo                      3D-map resorts (index.json from resorts/geo and data/geo)
GET /geo?resort=vail          that resort's runs and lifts as GeoJSON (made by extract.py)
POST /feedback                {resort, like: [run ids], dislike: [run ids], levels: {difficulty: 0-2}, note}
"""

import json
import sys
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import quasar

ROOT = Path(__file__).parent
RESORTS = ROOT / "resorts"
GEO_DIRS = [ROOT / "data" / "geo", RESORTS / "geo"]  # curated last so it wins on a slug clash
FEEDBACK = ROOT / "feedback.jsonl"
MAX_BODY = 64_000
MAX_MINUTES = 480  # a full ski day; beam search keeps big resorts to a few seconds


@lru_cache(maxsize=32)  # ponytail: built once per process; restart serve.py after rebuilding a resort
def resort(name):
    return quasar.load(RESORTS / f"{name}.json")


def resort_names():
    return sorted(p.stem for p in RESORTS.glob("*.json"))


def geo_index():
    """slug -> (index entry, geojson path) across the curated and on-demand extracts."""
    out = {}
    for d in GEO_DIRS:
        if (d / "index.json").exists():
            out |= {r["slug"]: (r, d / f"{r['slug']}.geojson") for r in json.loads((d / "index.json").read_text())}
    return out


def feedback(body):
    """Validates a feedback submission and appends it to feedback.jsonl. Body is untrusted."""
    try:
        fb = json.loads(body)
        geo = geo_index()[fb["resort"]]
        ids = {f["properties"]["id"] for f in json.loads(geo[1].read_text())["features"]}
        rec = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "resort": fb["resort"],
            "like": [i for i in fb.get("like", []) if i in ids],
            "dislike": [i for i in fb.get("dislike", []) if i in ids],
            "levels": {str(k)[:20]: int(v) for k, v in fb.get("levels", {}).items() if int(v) in (0, 1, 2)},
            "note": str(fb.get("note", ""))[:1000],
        }
    except (ValueError, KeyError, TypeError, AttributeError):
        return 400, {"error": "bad feedback"}
    with FEEDBACK.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return 200, {"ok": True}


def api(path, q):
    """Returns (status, body). Query values are untrusted: resort must be a known file, start/end real nodes."""
    if path == "/resorts":
        return 200, resort_names()
    if path == "/geo":
        geo = geo_index()
        if "resort" not in q:
            return 200, sorted((r for r, _ in geo.values()), key=lambda r: r["name"])
        if q["resort"] not in geo:
            return 400, {"error": "unknown resort"}
        return 200, json.loads(geo[q["resort"]][1].read_text())
    name = q.get("resort", "")
    if name not in resort_names():
        return 400, {"error": f"unknown resort {name!r}"}
    r = resort(name)
    if path == "/resort":
        return 200, {k: r.get(k) for k in ("name", "base", "nodes", "edges", "info", "source", "origin_lonlat")}
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
        pages = {"/": "viz.html", "/3d": "map3d.html"}
        if url.path in pages:
            self.send(200, (ROOT / pages[url.path]).read_bytes(), "text/html; charset=utf-8")
        else:
            status, data = api(url.path, {k: v[0] for k, v in parse_qs(url.query).items()})
            self.send(status, json.dumps(data).encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        if urlparse(self.path).path != "/feedback" or not 0 < n <= MAX_BODY:
            return self.send(400, b'{"error": "bad request"}')
        status, data = feedback(self.rfile.read(n))
        self.send(status, json.dumps(data).encode())

    def send(self, status, body, ctype="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    assert api("/plan", {"resort": "toy", "start": "summit", "minutes": "25"})[1]["vertical_m"] == 1400
    assert api("/plan", {"resort": "../quasar", "minutes": "25"})[0] == 400
    assert api("/plan", {"resort": "toy", "start": "nowhere", "minutes": "25"})[0] == 400
    assert api("/plan", {"resort": "toy", "minutes": "1e9"})[0] == 400
    assert api("/geo", {"resort": "../serve"})[0] == 400
    vail = api("/geo", {"resort": "vail"})[1]["features"]
    run = next(f["properties"]["id"] for f in vail if f["properties"]["kind"] == "run")
    FEEDBACK, real = ROOT / "feedback.selftest.jsonl", FEEDBACK
    assert feedback(json.dumps({"resort": "nope"}))[0] == 400
    assert feedback(b"not json")[0] == 400
    assert feedback(json.dumps({"resort": "vail", "levels": {"easy": 7}}))[0] == 200  # out-of-range level dropped
    assert feedback(json.dumps({"resort": "vail", "like": [run, "forged"], "note": "x" * 5000}))[0] == 200
    rec = json.loads(FEEDBACK.read_text().splitlines()[-1])
    assert rec["like"] == [run] and len(rec["note"]) == 1000
    FEEDBACK.unlink()
    FEEDBACK = real
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"QUASAR visualizer on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
