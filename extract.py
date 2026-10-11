"""Cut per-resort 3D map files out of the OpenSkiData dump.

python extract.py          # the 50 curated US resorts -> resorts/geo/ (committed)
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

# 50 popular US resorts, picked by approximate skier visits (no official per-resort numbers), across all US regions.
# slug -> OpenSkiData ski area id.
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
    # 30 more, for 50 in all
    "arapahoe-basin": "1e281ff389476a82150ad7ef7be5f1ea48edd5e5",
    "loveland": "1dd2321e1ddaeaba8ad3d040cd145bd2ad08c028",  # Loveland Basin, not the small Valley area
    "eldora": "1f25a1eacb8cc9814282d91ae00fd9af7a533d0e",
    "crested-butte": "c7ba44969ddc615ea94968125fc96d9b584c388f",
    "aspen-mountain": "2a2d5ad1138c3aac0abe644e073bee96589412d4",
    "aspen-highlands": "0469463129ab65721499780f98a6394662564f32",
    "purgatory": "66ebd7d72089d0697f49126b4fe6bfadbb08f9e0",
    "brighton": "ab2b5807422f8a412c013e32e73b521f76a65d98",
    "solitude": "b40e925163e2330550f940711b8571409fafb3a4",
    "snowbasin": "423504a1fa53bcfbe5bf956f0cd48c12868c7f06",
    "sun-valley": "b9ec1edd75823059c063c7c7b2a4078cf82542ab",  # Bald Mountain, Sun Valley's main mountain
    "mt-bachelor": "df0ebcea3daf2a4ad2c46e99f043d37d57cf1b9b",
    "mt-hood-meadows": "effda1f2db54d33bc3770670cd4335bd56a41eec",
    "crystal-mountain-washington": "89f555b5b8a62c0c002adaa796997b635f38e6da",  # same area as its QWOA pods
    "stevens-pass": "53a4f73effb0655bdb69989c1fb297c8206d04dc",
    "kirkwood": "718db266e6e9ec76a5003a404aec69a657b3ab33",
    "northstar": "717fe0e81e226ce0361fb10dc24e9f863eeda6ba",
    "bear-mountain": "78bac1237b378a398d712ba2cc962ddf9d1c6479",
    "taos": "8faa21d51bf5725e795c0972acbe92178a458347",
    "sugarloaf": "ba6f009c039cdf1008684fbf790a3fef14ec068a",
    "sunday-river": "54bceeb62ccd2209e50b8dc7e06b8daa1727ce34",
    "okemo": "f6908eabbb258d109d1b4c9f86f83620dcd69380",
    "stratton": "856ac5fd0830012a280f9d3939ff687676b429c1",
    "mount-snow": "74dd4473e21693f4e2d2fdfb66ed5eee9493d4cc",
    "sugarbush": "51088afbd7eaf31cf6e677c0b2b6e3ca621754ba",
    "loon": "84db66751dfc13969441d94cb66617193fe7407d",
    "whiteface": "d8b3d7d48706c9ce19bd6ba147c156ae89574ad8",
    "snowshoe": "1facaf3d92da6719b1c7aa95f763fbeda72222b3",
    "grand-targhee": "84ddf46f67c0fca577dc969188dc189f1c7a040f",
    "whitefish": "a9b9ab0ad6bb668e32b74a1745baa5974cdef3ec",
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
    """Length, drop and pitch from the line and its ~25 m DEM profile.

    Max pitch is per sample, so DEM noise can inflate it. None for area (polygon) runs."""
    if geom["type"] != "LineString" or not profile or len(profile.get("heights", [])) < 2:
        return {}
    c, h, res = geom["coordinates"], profile["heights"], profile["resolution"]
    length = sum(haversine_m(a, b) for a, b in itertools.pairwise(c))
    vertical = abs(h[0] - h[-1])  # top-to-bottom drop, not elevation range
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
    if p.get("status") != "operating":  # same rule as the planner graph
        return False
    return p["type"] == "lift" or "downhill" in (p.get("uses") or [])


def extract(areas, out):
    """areas: {ski_area_id: slug}. Writes <slug>.geojson per area plus index.json."""
    out.mkdir(parents=True, exist_ok=True)
    # ponytail: holds every kept feature in memory (~GBs for --all); stream to files if RAM runs out
    groups = defaultdict(list)
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
