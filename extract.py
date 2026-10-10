"""Cut per-resort 3D map files out of the OpenSkiData dump.

python extract.py          # the 20 curated US resorts -> resorts/geo/ (committed)
python extract.py --all    # every downhill ski area   -> data/geo/ (local, slow)

Reads data/openskidata/{ski_areas,runs,lifts}.geojson, which hold one feature per line,
so one streaming pass with the stdlib json module is enough.
"""

import argparse
import itertools
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
SRC = ROOT / "data" / "openskidata"

# Most-visited US resorts (approximate annual skier visits). slug -> OpenSkiData ski area id.
TOP_US = {
    "vail": "88a22ba23468cf120025366ef40f004c9043546e",
    "breckenridge": "e1eb4ed2f10fc217647fa66ff48d640814d0c4f7",
    "park-city": "3dad9d62b112c018cb658fd1eb49bcd41c96f257",
    "mammoth": "ba4944ecd2e640acedf666287f228427b607680e",
    "keystone": "7d855b81e131f7cb7bdbc7b55e47a18d3ccb5e67",
    "steamboat": "1b452491f464540026e80e10ab6d7290b414c1f6",
    "copper-mountain": "0bab3102857cf4c7243d3db844c283a24413fa28",
    "winter-park": "eac3283b22abc1d56081b11e2c4867209961f982",
    "heavenly": "3f61859b47be735a77df9b1b9e102edbeb529286",
    "palisades-tahoe": "fa7bea0bfe372c06b3cccc3e8113949837d688fb",
    "killington": "ac774efde21231d04a2cd3a7b6cfd380dfcb4bef",
    "beaver-creek": "7017f6efbc9eec1b154159dc64b3c62edad86e57",
    "big-sky": "d4086b2e9d44022ca27bde811816b5a4fc859c87",
    "jackson-hole": "2b812055300b5107fc2ffed8f5ae27a4c4f94f0a",
    "deer-valley": "b7a200210f3dac1b9a5ca7b71429e6205c8c413e",
    "snowmass": "ab35349ba4e03d734a486561e99d5be0b772449f",
    "snowbird": "3c02f21915683b910d389339bda960dc05e18314",
    "alta": "80b43d73222ff9f4c560fcb7417278f351f5b64c",
    "stowe": "1688ce1f44c0112805d9755f31a8e82283162cfb",
    "telluride": "c036edc54d4fe7d4c6f93de5b9f3dcaff34a5a64",
}


def features(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if line.startswith("{") and "FeatureCollection" not in line:
                yield json.loads(line)


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def haversine_m(a, b):
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    )
    return 2 * 6371000 * math.asin(math.sqrt(h))


def run_stats(geom, profile):
    """Length, vertical and pitch from the line and its 25 m elevation profile. None for area (polygon) runs."""
    if geom["type"] != "LineString" or not profile or len(profile.get("heights", [])) < 2:
        return {}
    c, h, res = geom["coordinates"], profile["heights"], profile["resolution"]
    length = sum(haversine_m(a, b) for a, b in itertools.pairwise(c))
    vertical = max(h) - min(h)
    steepest = max(abs(b - a) for a, b in itertools.pairwise(h))
    return {
        "length_m": round(length),
        "vertical_m": round(vertical),
        "avg_pitch": round(math.degrees(math.atan2(vertical, length or 1))),
        "max_pitch": round(math.degrees(math.atan2(steepest, res))),
        "profile": [round(x) for x in h],
    }


def round_coords(c):
    return [round(c[0], 5), round(c[1], 5), round(c[2])] if isinstance(c[0], float) else [round_coords(x) for x in c]


def slim(f):
    p, g = f["properties"], f["geometry"]
    g = {"type": g["type"], "coordinates": round_coords(g["coordinates"])}
    if p["type"] == "lift":
        props = {k: p.get(k) for k in ("id", "name", "liftType", "capacity", "duration")}
    else:
        props = {k: p.get(k) for k in ("id", "name", "difficulty", "gladed", "lit", "grooming")}
        props["convention"] = p.get("difficultyConvention")
        props |= run_stats(f["geometry"], p.get("elevationProfile"))
    return {"type": "Feature", "geometry": g, "properties": {"kind": p["type"], **props}}


def wanted(f):
    p = f["properties"]
    if p.get("status") not in (None, "operating"):
        return False
    return p["type"] == "lift" or "downhill" in (p.get("uses") or [])


def extract(areas, out):
    """areas: {ski_area_id: slug}. Writes <slug>.geojson per area plus index.json."""
    out.mkdir(parents=True, exist_ok=True)
    groups = defaultdict(
        list
    )  # ponytail: holds every kept feature in memory (~GBs for --all); stream to files if RAM runs out
    for name in ("runs", "lifts"):
        for f in features(SRC / f"{name}.geojson"):
            ids = [a["properties"]["id"] for a in f["properties"].get("skiAreas", [])]
            if any(i in areas for i in ids) and wanted(f):
                s = slim(f)
                for i in ids:
                    if i in areas:
                        groups[i].append(s)
    index = []
    for f in features(SRC / "ski_areas.geojson"):
        p = f["properties"]
        if p["id"] not in groups:
            continue
        slug = areas[p["id"]]
        (out / f"{slug}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": groups[p["id"]]}, separators=(",", ":"))
        )
        hint = p.get("viewportHint") or {}
        index.append(
            {
                "slug": slug,
                "name": p["name"],
                "region": (p.get("places") or [{}])[0].get("iso3166_2"),
                "center": hint.get("center"),
                "bearing": round(hint.get("bearing") or 0),
            }
        )
    index.sort(key=lambda r: r["name"])
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"wrote {len(index)} resorts to {out}")


def all_downhill_areas():
    areas = {}
    for f in features(SRC / "ski_areas.geojson"):
        p = f["properties"]
        if "downhill" in p.get("activities", []) and p.get("name"):
            areas[p["id"]] = f"{slugify(p['name'])}-{p['id'][:6]}"
    return areas


if __name__ == "__main__":
    assert slugify("Palisades Tahoe — Olympic Valley") == "palisades-tahoe-olympic-valley"
    assert (
        run_stats(
            {"type": "LineString", "coordinates": [[0, 0, 100], [0, 0.001, 0]]},
            {"heights": [100, 50, 0], "resolution": 50},
        )["max_pitch"]
        == 45
    )
    assert run_stats({"type": "Polygon", "coordinates": []}, None) == {}
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="every downhill ski area into data/geo/")
    a = ap.parse_args()
    if a.all:
        extract(all_downhill_areas(), ROOT / "data" / "geo")
    else:
        extract({v: k for k, v in TOP_US.items()}, ROOT / "resorts" / "geo")
