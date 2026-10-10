# QUASAR — Quantitative Unique Alpine Ski Altitude Routing

Given where a skier is now and how much time they have, find a near-optimal route that covers the most *unique* vertical. A run scores its full vertical the first time and half on repeats. Repeat lift rides cost a little.

## Problem

We model a ski resort as a directed graph. Nodes are trail junctions and lift terminals. Runs give vertical drop and take time. Lifts only take time. Walk links are short walks or skates that bridge gaps in the map data. They can be repeated, and any height they climb is subtracted from the score, so a route can't farm points by skiing a dip and walking back up. A **route** is a walk from the skier's current node to a finish node (by default the base) that fits inside their **time budget**.

```text
maximize   Σ vertical(first descent of each run)  +  RUN_REPEAT_CREDIT × Σ vertical(repeat descents)
           − LIFT_REPEAT_COST × (repeat lift rides)            [defaults: 0.5 and 50 m]
subject to total minutes ≤ budget,  walk starts at `start` and ends at `end`
```

Repeats have to be allowed. On real resorts, many trails funnel into a few run-outs back to the base, so a strict "each run once" rule caps a day at two or three laps. Partial credit means a typical repeat lap (300–700 m of drop) still nets +100 to +300, so long budgets fill the day once the new runs run out, while new runs are still worth twice as much. Crystal at 480 min plans 480 min and 12,100 m. The planner returns two numbers: `score`, which is the objective above, and `vertical_m`, which is everything skied, repeats included.

Because of the time budget, this is an orienteering / prize-collecting problem, which is NP-hard.

The classical solver works in two tiers:
- **Exact branch-and-bound** for small resorts. It never takes a leg that leaves too little time to get back.
- **Beam search** for real resorts (more than 60 edges), or when the exact search would visit more than 300k nodes. It keeps the 500 best partial routes per minute, at most 5 per junction so one spot can't crowd out the rest. Results are flagged `optimal: false`.

The quantum side is **QWOA**: QAOA whose mixer is a continuous-time quantum walk over the feasible routes ([Marsh & Wang 2020](https://arxiv.org/abs/1912.07353)). Every state the walk reaches is a valid route, so no probability is spent on invalid ones, which is unlike a penalty QUBO with the standard X mixer. QWOA's results are reported as **near-optimal** and compared with the exact optimum.

## Scale

| Instance (90 min budget) | Edges | Feasible routes \|F\| | B&B tree T | QWOA qubits ⌈log₂\|F\|⌉ |
| --- | --- | --- | --- | --- |
| Toy Peak | 9 | 428 | 9,168 | 9 |
| 1 lift pod (synthetic) | 7 | 876 | 1.5 × 10⁵ | 10 |
| 3 lift pods (synthetic) | 23 | 30,643 | 1.5 × 10⁶ | 15 |
| 4 lift pods (synthetic) | 31 | 181,268 | 2.0 × 10⁷ | 18 |
| Crystal Mountain, WA (real) | 434 | can't enumerate | beam search only | — |
| Whistler Blackcomb (real) | 3,340 | can't enumerate | beam search only | — |

- On synthetic resorts, the B&B tree grows by about 10^0.09 per extra lift or run. The budget sets the tree depth (budget ÷ shortest edge), so longer days also mean much bigger trees.
- Real resorts are already past exact search. Across the 22 included resorts, a 2-hour plan takes at most 1.7 s. A full 8-hour day takes 4–19 s; Whistler is the slowest.
- **Near-term (IonQ):** run QWOA on single lift pods with a few hundred routes. The feasible routes are indexed classically, which is fine for validating the algorithm but gives no quantum advantage.

## Quantum speedup (large fault-tolerant machine)

`speedup.py` measures the size T of the classical branch-and-bound tree on growing synthetic resorts. It compares T with the cost of a quantum-walk search of the same tree:

- **Backtracking quantum walk** ([Montanaro 2018](https://arxiv.org/abs/1509.02374)) takes O(√T · n^1.5 · log n) steps, where n is the tree depth. For optimization, [Montanaro 2020](https://arxiv.org/abs/1906.10375) gives a near-quadratic speedup over classical branch-and-bound in a very general setting. That result needs known bounds on the cost range and adds log factors. This is the speedup we claim. It walks the tree with local moves, so it doesn't need the routes to be enumerated first.
- **Grover / Dürr–Høyer minimum finding** over all |F| routes takes √|F| steps versus |F|. This is the upper limit for the complete-graph QWOA mixer. QWOA itself has no proven speedup; it's a heuristic.

Measured with a 90-minute budget (`python speedup.py`; the 39-edge row comes from `--max-zones 5`):

| edges | B&B tree T | depth n | quantum steps | step speedup |
| --- | --- | --- | --- | --- |
| 7 | 1.5 × 10⁵ | 18 | 1.2 × 10⁵ | 1.2× |
| 15 | 4.9 × 10⁵ | 18 | 2.2 × 10⁵ | 2.2× |
| 23 | 1.5 × 10⁶ | 18 | 3.9 × 10⁵ | 3.8× |
| 31 | 2.0 × 10⁷ | 21 | 1.9 × 10⁶ | 10.6× |
| 39 | 8.5 × 10⁷ | 21 | 3.9 × 10⁶ | 21.8× |

A step on an error-corrected machine is much slower than a classical step (`--overhead`, assumed to be 10⁴). Because of that, the quadratic speedup only shows up in wall-clock time once T > (overhead · n^1.5 · log n)² ≈ 1.8 × 10¹³ nodes. By extrapolating the five-size fit, that's a resort with roughly **100 lifts+runs** (99). All 22 real resorts (434–3,340 edges) are well past that size. The speedup is quadratic, not exponential, so the overhead matters a lot ([Babbush et al. 2021](https://arxiv.org/abs/2011.04149)).

## Run

```sh
pip install -r requirements.txt
python quasar.py --minutes 60                       # toy resort from the base, plus the QWOA demo
python quasar.py --start summit --minutes 25        # skier is at the summit
python quasar.py resorts/whistler-blackcomb.json --minutes 120   # real resort (beam search)
python quasar.py --minutes 90 --json                # plan only, for the app / visualizer
python speedup.py                                   # speedup table (~3 min; --max-zones 5 takes ~20 min)
```

## Visualizer

```sh
python serve.py [port]    # then open http://localhost:8000 (or your port)
```

The visualizer draws the resort map:
- runs are solid blue lines, lifts are dashed grey, and walk links are dotted;
- on real resorts, labels are hidden; hover over a line or junction to see its name.

Click a junction, or use the dropdown, to set where the skier is, then set the minutes they have left. The route appears in orange, labeled either proven optimal or near-optimal (beam search). The side panel shows the step list and the resort's Global Ski Atlas facts, if the atlas lists it.

`serve.py` is a standard-library JSON API (`/resorts`, `/resort`, `/plan`, `/geo`, `POST /feedback`) that the app can reuse.

## 3D mountain map

```sh
python serve.py [port]    # then open http://localhost:8000/3d (or your port)
```

Each resort is shown in 3D: satellite imagery and hillshade over terrain, with runs colored by difficulty (European colors for European resorts, North American colors elsewhere) and lifts as dashed lines. Click a run to see its elevation profile, length, vertical drop, and average and steepest pitch (the steepest is per 25 m elevation sample, so treat it as approximate). Mark a run 👍 or 👎, rate each skill level (Skip, Maybe or Want), then **Send feedback** to append the choices to `feedback.jsonl`. **Copy link** shares the current view, the runs you voted on and your skill-level choices.

Twenty popular US resorts, picked by approximate skier visits, are already included in `resorts/geo/`. They are cut from the [OpenSkiData](https://openskimap.org) dump in `data/openskidata/`:

```sh
python extract.py          # rebuild the 20 curated resorts (took 14 s on a laptop)
python extract.py --all    # every downhill ski area into data/geo/ (local only; served alongside the curated set)
```

## Resort data

The raw datasets go in `data/`, which is gitignored (~1.1 GB):
- `data/openskidata/`: OpenSkiMap GeoJSON with 3D runs and lifts.
- `data/global-ski-atlas/`: Global Ski Atlas parquet files.

Build a resort graph from them:

```sh
python datasets.py "Crystal Mountain" --region Washington   # -> resorts/crystal-mountain-washington.json
python datasets.py "Whistler Blackcomb"                     # -> resorts/whistler-blackcomb.json
python datasets.py --top-us                                 # the 3D map's 20 resorts, same slugs (~2 min)
```

The routing graphs cover 22 resorts: Crystal Mountain (WA), Whistler Blackcomb, and the 3D map's 20 US resorts. The 20 use the 3D map's slugs and OpenSkiMap ids (`extract.TOP_US`), so `resorts/vail.json` and `resorts/geo/vail.geojson` describe the same ski area.

- **OpenSkiMap** provides the graph. Only lines that mention the ski area's id get parsed, so a 1 GB scan takes about 2 s.
  - Run and lift ends within 40 m are merged into one junction.
  - Runs are split wherever another trail joins them.
  - Walk links of up to 250 m bridge gaps in the map data. They may climb at most 15 m.
  - Lifts tagged two-way, and untagged gondolas, cable cars and funiculars, can be ridden down as well as up (village and transfer gondolas, trams). Chairs only go down when tagged.
  - Run times come from length at 4 m/s. Lift times come from duration or speed by lift type, plus 3 minutes of waiting.
  - These settings are calibration knobs at the top of `datasets.py`.
  - Junctions that can't make a round trip from the base are dropped, and the build names the lifts that are lost this way. 12 of the 20 resorts keep every lift. Big Sky (5 lost) and Snowmass (4) have the largest gaps.
  - The default base is the lift bottom in the lowest quarter of the resort's elevation where the most runs finish. In the app, the skier picks their own start anyway.
- **Global Ski Atlas** adds catalogue facts (`info`: lift and trail counts, website) and a lift-count cross-check. Its coverage is partial: Crystal Mountain WA isn't listed, and vertical drop is often missing.
- **Known data issues:**
  - Run direction comes from the order of points in the map data.
  - A few segments climb slightly. They score 0 vertical.
  - "Express" chairs are assumed to be detachable because OpenSkiMap rarely tags it.

Each `resorts/*.json` file contains:
- `nodes`: `{name: [x, y, elevation_m]}`, with x and y in local metres from `origin_lonlat`.
- `lifts` / `runs` / `links`: `[[name, from, to, minutes], ...]`. Run vertical is calculated from node elevations.
- `base`: the default start and finish node.
- `info`, `source`: atlas facts and data provenance.

## Contributing

`main` only changes through pull requests. Every feature goes on its own branch (`feature/<name>`) and is merged through a pull request after CI passes. CI checks ruff lint and formatting (ruff pinned in `requirements.txt`), and runs the planner, beam search, QWOA and visualizer self-checks plus a small speedup analysis.

```sh
git switch main && git pull
git switch -c feature/<name>
# ...work...
python -m ruff format . && python -m ruff check .
git push -u origin feature/<name>   # then open a PR into main
```
