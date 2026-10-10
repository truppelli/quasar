"""Build QUASAR resort graphs from the raw datasets in data/ (gitignored, ~1 GB).

    python datasets.py "Crystal Mountain" --region Washington    -> resorts/crystal-mountain-washington.json
    python datasets.py --top-us                                  -> the 3D map's 20 resorts, same slugs (resorts/vail.json)

OpenSkiMap (data/openskidata) gives the routing graph: 3D run and lift lines tagged with their ski area.
Global Ski Atlas (data/global-ski-atlas) gives catalogue stats (lift/trail counts, website) stored as "info" and,
when it lists the resort, a lift-count cross-check. Coverage is partial and vertical drop is often missing.
"""

import argparse
import itertools
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).parent
OSD = ROOT / "data" / "openskidata"
GSA = ROOT / "data" / "global-ski-atlas"

# Calibration knobs: real lifts and skiers vary, tune these against what skiers actually report.
SNAP_M = 40  # trail ends closer than this are one junction
LINK_M = 250  # walk/skate links bridge mapping gaps up to this far (lift top -> run, run end -> lift, dead ends)
LINK_CLIMB_M = 15  # a link may climb at most this much (chained walks up to 2 * LINK_M are merged into one)
WALK_MPS = 1.2
SKI_SPEED_MPS = 4.0  # average descent speed including short stops
LIFT_WAIT_MIN = 3.0  # line + load time per ride
LIFT_SPEED_MPS = {"gondola": 5.0, "cable_car": 8.0, "chair_lift": 2.3, "detachable": 5.0, "magic_carpet": 0.8}
DRAG_SPEED_MPS = 3.0  # t-bar, platter, rope tow, anything else


def features(path, needle):
    """Stream a line-per-feature GeoJSON; only lines containing `needle` are parsed (1 GB scans in seconds)."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if needle in line:
                yield json.loads(line.strip().rstrip(","))


def find_area(name, region=None):
    areas = [
        a["properties"]
        for a in features(OSD / "ski_areas.geojson", json.dumps(name)[1:-1])
        if a["properties"]["name"] == name and "downhill" in a["properties"]["activities"]
    ]
    if region:
        areas = [a for a in areas if any(region in json.dumps(p["localized"]) for p in a["places"])]
    if not areas:
        near = {
            a["properties"]["name"]
            for a in features(OSD / "ski_areas.geojson", json.dumps(name)[1:-1])
            if "downhill" in a["properties"]["activities"]
        }
        raise SystemExit(f"no downhill ski area named exactly {name!r}; close matches: {sorted(near)[:20]}")
    if len(areas) != 1:
        where = [(a["id"], [p["localized"]["en"]["region"] for p in a["places"]]) for a in areas]
        raise SystemExit(f"{len(areas)} downhill ski areas named {name!r}{' in ' + region if region else ''}: {where}")
    return areas[0]


def atlas_info(area):
    """Global Ski Atlas stats for the same resort (matched on name + state/country), or {} if it isn't listed."""
    import pyarrow.parquet as pq

    place = area["places"][0]["localized"]["en"] if area["places"] else {}
    rows = [
        r
        for r in pq.read_table(GSA / "ski_areas_analyzed.parquet").to_pylist()
        if area["name"] in (r["name"], r["english_name"])
        and r["state"] == place.get("region")
        and (r["country"] or "").startswith(place.get("country") or "?")  # "United States" vs "... of America"
    ]
    keep = ("country", "state", "total_lifts", "downhill_trails", "elevation_low_m", "elevation_high_m",
            "vertical_drop_m", "website")  # fmt: skip
    return {k: rows[0][k] for k in keep} if len(rows) == 1 else {}


def lift_speed(p):
    t = p["liftType"]
    detachable = p.get("detachable")
    if detachable is None:  # unset on ~98% of OpenSkiMap lifts; "Express" chairs are detachable in practice
        detachable = "express" in (p["name"] or "").lower()
    if t == "chair_lift" and detachable:
        t = "detachable"
    return LIFT_SPEED_MPS.get(t, DRAG_SPEED_MPS)


def _two_way(p):
    """Ridable down too: tagged oneway=no, or an untagged cabin lift (village/transfer gondolas, trams)."""
    # ponytail: chairs are only two-way when tagged; tag-free download chairs are rare enough to skip
    return p.get("oneway") is False or (
        p.get("oneway") is None and p["liftType"] in ("gondola", "cable_car", "funicular")
    )


def build_graph(area):
    aid = area["id"]

    def mine(f):  # operating only, same rule as the 3D map's extract.py
        p = f["properties"]
        ours = any(a["properties"]["id"] == aid for a in p.get("skiAreas") or [])
        return ours and p["status"] == "operating"

    runs = [f for f in features(OSD / "runs.geojson", aid) if mine(f) and "downhill" in f["properties"]["uses"]]
    lifts = [f for f in features(OSD / "lifts.geojson", aid) if mine(f)]
    # ponytail: area-shaped runs (Polygon bowls) skipped; add when a resort's bowls matter for routing
    runs = [f for f in runs if f["geometry"]["type"] == "LineString"]

    lon0, lat0 = area_center = _center(runs + lifts)
    kx = 111320 * math.cos(math.radians(lat0))

    def local(c):
        return ((c[0] - lon0) * kx, (c[1] - lat0) * 110540, c[2] if len(c) > 2 else 0.0)

    lines = [(f, _densify([local(c) for c in f["geometry"]["coordinates"]])) for f in runs + lifts]

    # junctions = clustered endpoints  # ponytail: O(n^2) clustering, fine for one resort's few hundred ends
    clusters = []  # [x, y, [z...], names]

    def cluster_of(pt, add=False):
        for c in clusters:
            if math.dist(pt[:2], c[:2]) <= SNAP_M:
                return c
        if add:
            clusters.append([pt[0], pt[1], [], []])
            return clusters[-1]

    for f, pts in lines:
        for pt in (pts[0], pts[-1]):
            cluster_of(pt, add=True)[2].append(pt[2])

    edges = []  # (kind, name, from_cluster, to_cluster, length_m, props)
    for f, pts in lines:
        p = f["properties"]
        name = p["name"] or p["ref"] or ("Unnamed " + p["type"])
        if p["type"] == "lift":
            a, b = cluster_of(pts[0]), cluster_of(pts[-1])
            if pts[0][2] > pts[-1][2]:
                a, b = b, a
            a[3].append(f"{name} bottom")
            b[3].append(f"{name} top")
            edges.append(("lift", name, a, b, _length(pts), p))
            if _two_way(p):
                edges.append(("lift", name, b, a, _length(pts), p))
            continue
        # split the run wherever it passes a junction (another trail joining mid-run)
        cuts = [(i, c) for i, pt in enumerate(pts) if (c := cluster_of(pt))]
        cuts = [cut for k, cut in enumerate(cuts) if k == 0 or cut[1] is not cuts[k - 1][1]]
        for (i, a), (j, b) in itertools.pairwise(cuts):
            edges.append(("run", name, a, b, _length(pts[i : j + 1]), p))
            a[3].append(name)
            b[3].append(name)

    # links: short walks/skates across gaps where the map's trails don't quite touch
    starts = {id(e[2]) for e in edges}
    lift_ends = {id(e[2]) for e in edges if e[0] == "lift"} | {id(e[3]) for e in edges if e[0] == "lift"}
    z = {id(c): sum(c[2]) / len(c[2]) for c in clusters}
    for a in clusters:
        for b in clusters:
            d = math.dist(a[:2], b[:2])
            if (
                a is not b
                and d <= LINK_M
                and z[id(b)] <= z[id(a)] + LINK_CLIMB_M
                and (id(a) not in starts or id(a) in lift_ends or id(b) in lift_ends)
            ):
                edges.append(("link", "walk", a, b, d, {}))
    # chained walks become one direct link, so the planner never needs two links in a row
    walk = {(id(e[2]), id(e[3])): e[4] for e in edges if e[0] == "link"}
    by_id = {id(c): c for c in clusters}
    for k in by_id:  # ponytail: Floyd-Warshall over junctions, fine for a few hundred
        for (i, j), d1 in list(walk.items()):
            if j == k:
                for (k2, m), d2 in list(walk.items()):
                    if k2 == k and m != i and d1 + d2 <= 2 * LINK_M and d1 + d2 < walk.get((i, m), math.inf):
                        walk[(i, m)] = d1 + d2
    edges = [e for e in edges if e[0] != "link"]
    edges += [("link", "walk", by_id[i], by_id[j], d, {}) for (i, j), d in walk.items()]

    names = {}
    for c in clusters:
        label = next((n for n in c[3] if n.endswith((" bottom", " top"))), " / ".join(dict.fromkeys(c[3][:2])))
        k, base_label = 2, label or "junction"
        while label in names.values() or not label:
            label, k = f"{base_label} {k}", k + 1
        names[id(c)] = label

    resort = {
        "name": area["name"],
        "source": f"OpenSkiMap ski area {aid}",
        "origin_lonlat": list(area_center),
        "nodes": {names[id(c)]: [round(c[0]), round(c[1]), round(sum(c[2]) / len(c[2]), 1)] for c in clusters},
        "lifts": [],
        "runs": [],
        "links": [],
    }
    for kind, name, a, b, length, p in edges:
        if a is b:
            continue
        if kind == "lift":
            mins = (p["duration"] / 60 if p.get("duration") else length / lift_speed(p) / 60) + LIFT_WAIT_MIN
        else:
            mins = length / (SKI_SPEED_MPS if kind == "run" else WALK_MPS) / 60
        resort[kind + "s"].append([name, names[id(a)], names[id(b)], round(max(mins, 0.5), 1)])
    return _keep_base_component(resort)


def _center(feats):
    pts = [c for f in feats for c in f["geometry"]["coordinates"]]
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _densify(pts, step=10.0):
    """Extra points every `step` m so junctions part-way along a sparse line are still found."""
    out = [pts[0]]
    for p, q in itertools.pairwise(pts):
        n = max(1, int(math.dist(p[:2], q[:2]) // step))
        out += [tuple(a + (b - a) * k / n for a, b in zip(p, q)) for k in range(1, n + 1)]
    return out


def _length(pts):
    return sum(math.dist(p, q) for p, q in itertools.pairwise(pts))


def _keep_base_component(r):
    """Base = the lift bottom with the biggest round-trip network (ties: most runs ending there); drop junctions
    outside it (mapping gaps)."""
    es = r["lifts"] + r["runs"] + r["links"]

    def reach(start, fwd):
        seen, stack = {start}, [start]
        while stack:
            n = stack.pop()
            for _, u, v, _ in es:
                a, b = (u, v) if fwd else (v, u)
                if a == n and b not in seen:
                    seen.add(b)
                    stack.append(b)
        return seen

    z = {n: v[2] for n, v in r["nodes"].items()}
    bottoms = {u for _, u, v, _ in r["lifts"] if z[u] < z[v]}  # uphill direction only (two-way lifts run both)
    # ponytail: one DFS pair per lift bottom, fine for tens of lifts
    loops = {n: reach(n, True) & reach(n, False) for n in bottoms}
    keep = max(loops.values(), key=len)
    # base area = low and busy: among bottoms in the network's lowest quarter, the one most runs finish at
    lo, hi = min(z[n] for n in keep), max(z[n] for n in keep)
    runs_in = {}
    for _, _, v, _ in r["runs"]:
        runs_in[v] = runs_in.get(v, 0) + 1
    low = [n for n in bottoms if n in keep and z[n] <= lo + (hi - lo) / 4]
    r["base"] = max(low, key=lambda n: (runs_in.get(n, 0), -z[n]))
    dropped = sorted({e[0] for e in r["lifts"] if e[1] not in keep or e[2] not in keep})
    r["nodes"] = {k: v for k, v in r["nodes"].items() if k in keep}
    for kind in ("lifts", "runs", "links"):
        r[kind] = [e for e in r[kind] if e[1] in keep and e[2] in keep]
    return r, dropped


def write(area, slug):
    resort, dropped_lifts = build_graph(area)
    resort["info"] = atlas_info(area)
    out = ROOT / "resorts" / f"{slug}.json"
    out.write_text(json.dumps(resort, indent=1, ensure_ascii=False), encoding="utf-8")

    elev = [n[2] for n in resort["nodes"].values()]
    lifts = len({e[0] for e in resort["lifts"]})
    print(f"{out.relative_to(ROOT)}: {len(resort['nodes'])} junctions, {lifts} lifts, {len(resort['runs'])} run "
          f"segments, {len(resort['links'])} walk links, {max(elev) - min(elev):.0f} m vertical")  # fmt: skip
    if dropped_lifts:
        print(f"  lifts not connected to the base network (mapping gaps): {', '.join(dropped_lifts)}")
    if info := resort["info"]:
        print(f"  Global Ski Atlas: {info['total_lifts']} lifts, vertical {info['vertical_drop_m'] or 'n/a'} m")
    else:
        print("  not listed in Global Ski Atlas (no info or cross-check)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="ski area name exactly as in OpenSkiMap")
    ap.add_argument("--region", help="region or country to disambiguate, e.g. Washington")
    ap.add_argument("--top-us", action="store_true", help="build the 3D map's 20 resorts (extract.TOP_US slugs)")
    a = ap.parse_args()

    if a.top_us:
        from extract import TOP_US

        for slug, aid in TOP_US.items():
            area = next(
                f["properties"] for f in features(OSD / "ski_areas.geojson", aid) if f["properties"]["id"] == aid
            )
            write(area, slug)
    elif a.name:
        write(find_area(a.name, a.region), re.sub(r"[^a-z0-9]+", "-", f"{a.name} {a.region or ''}".lower()).strip("-"))
    else:
        ap.error("give a ski area name or --top-us")
