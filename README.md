# QUASAR — Quantitative Unique Alpine Ski Altitude Routing

Given where a skier is now and how much time they have, find a near-optimal route that covers the most *unique* vertical. A run scores its full vertical the first time and half on repeats. Repeat lift rides cost a little.

> **Qollab hackathon submission.** This effort is supported by Qollab & IonQ. Student Track, Quantum Impact theme, Colorado School of Mines node. MIT license. Run `python main.py` for the hackathon demo: QWOA against a penalty-QUBO QAOA baseline on one lift pod, with both circuits packed into one IonQ job ([details](#baseline-penalty-qubo-qaoa)). Demo video outline: [docs/demo-video.md](docs/demo-video.md). Credits: [contributions.md](contributions.md).

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
- **Beam search** when the exact search doesn't finish within 300k nodes (20k on graphs over 60 edges, so whole resorts lose only a fraction of a second; lift pods still finish exactly). It keeps the 500 best partial routes per minute, at most 5 per junction so one spot can't crowd out the rest. Results are flagged `optimal: false`.

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
- Real resorts are already past exact search. Across the 22 included resorts, a 2-hour plan takes at most 2.3 s. A full 8-hour day takes 6–22 s; Whistler is the slowest.
- **Near-term (IonQ):** run QWOA on single lift pods with a few hundred routes. The feasible routes are indexed classically, which is fine for validating the algorithm but gives no quantum advantage.

## Lift pods (QWOA-sized instances)

Real resorts are too big to enumerate, so for QWOA we split them into **lift pods**. A pod is one lift plus the runs and links that lead from its top back to its bottom without riding another lift or leaving that lift's elevation band (±20 m). Each pod is a small resort of its own, with its base at the lift's bottom station. For each pod, `--pods` finds the longest time budget (at least one lap) whose feasible routes still fit in 9 qubits (512 routes).

```sh
python quasar.py resorts/crystal-mountain-washington.json --pods                  # list pods and their QWOA sizes
python quasar.py resorts/crystal-mountain-washington.json --pod "Rainier Express"  # exact optimum + beam + QWOA on one pod
```

Measured with QWOA simulated at p=3 (`--pod`, default budgets):

| Crystal pod | budget | routes | qubits | P(optimal) QWOA vs random | beam vs optimal |
| --- | --- | --- | --- | --- | --- |
| Rainier Express | 18 min | 470 | 9 | 0.018 vs 0.006 | 95.8% |
| Green Valley | 28 min | 474 | 9 | 0.010 vs 0.002 | 100% |
| Mt. Rainier Gondola | 34 min | 254 | 8 | 0.018 vs 0.008 | 100% |
| Quicksilver | 25 min | 349 | 9 | 0.039 vs 0.011 | 100% |
| Gold Hills | 43 min | 471 | 9 | 0.019 vs 0.002 | 100% |
| Chinook Express | 22 min | 334 | 9 | 0.010 vs 0.003 | 100% |
| Discovery | 61 min | 506 | 9 | 0.014 vs 0.002 | 100% |
| Forest Queen Express | 16 min | 450 | 9 | 0.300 vs 0.011 | 100% |
| Magic Carpet | 59 min | 509 | 9 | 0.008 vs 0.002 | 100% |

- All 9 Crystal pods fit in 9 qubits. Only 9 of Whistler's 34 pods do: its map data splits trails into many short segments, so most pods have too many routes even for a single lap.
- QWOA beats random sampling on every pod, but at p=3 the chance of sampling the optimum stays in the low percent. Deeper circuits (larger p) are the next lever.
- Pods are QWOA instances, not a planner. They can overlap, and whole-day plans still run `plan()` on the full resort.

## QWOA circuit (Qiskit, IonQ)

`circuit.py` builds QWOA as a Qiskit circuit for one lift pod and checks it against the NumPy QWOA in `quasar.py`, using the same angles. It then samples 1,000 shots and compiles to IonQ's native gates (MS on Aria, ZZ on Forte). Compiling runs offline with `qiskit-ionq`: no API key and no job.

```sh
python circuit.py                                                   # toy pod, 6 qubits
python circuit.py resorts/crystal-mountain-washington.json --pod "Discovery" --max-routes 16 --p 1
```

- **How routes are encoded:** routes 0…M−1 are basis states of n = ⌈log₂ M⌉ qubits. Indices M and above never gain amplitude.
- **Each QWOA layer:** a phase separator (one diagonal gate, exp(−iγC)) followed by the walk mixer. The mixer is U · (phase on |0…0⟩) · U†, where U prepares the uniform state over valid routes.
- **Check:** the circuit's probabilities match the NumPy version to about 1e-14.

What it costs on hardware (Aria, two-qubit MS gates):

| qubits | p=1 | p=2 | p=3 |
| --- | --- | --- | --- |
| 3 | 24 | 44 | 64 |
| 4 | 55 | 103 | 151 |
| 6 | 185 | 357 | 529 |
| 9 | 900 | 1,778 | 2,656 |

(Measured on random scores with 3/4 of the register filled. Real pods cost more when M is awkward for state preparation: Rainier Express, with 470 routes on 9 qubits at p=3, needs 6,016.)

- **Too deep for today's hardware:** two-qubit errors compound, so the 9-qubit pods from `--pods` would return mostly noise.
- **First run on hardware:** 4 qubits, p=1, sized with `--max-routes 16`.

| Crystal pod (≤ 16 routes) | budget | routes | p | MS gates | P(optimal) vs random |
| --- | --- | --- | --- | --- | --- |
| Discovery | 18 min | 14 | 1 | 67 | 0.183 vs 0.071 |
| Mt. Rainier Gondola | 30 min | 15 | 1 | 67 | 0.508 vs 0.133 |
| Chinook Express | 18 min | 12 | 2 | 103 | 0.353 vs 0.083 |

## Baseline: penalty-QUBO QAOA

`qaoa.py` runs the textbook alternative on the same lift pod: standard QAOA with an X mixer over a penalty QUBO ([Lucas 2014](https://arxiv.org/abs/1302.5843)). It compares the result with QWOA at the same p, then packs both circuits into **one job** with `circuit.pack`, because an IonQ run takes one circuit. `circuit.unpack` splits the counts again.

```sh
python main.py                                                     # Qollab entry point: Crystal Quicksilver on the backend from Select QPU
python qaoa.py resorts/crystal-mountain-washington.json --pod "Quicksilver" --max-routes 4
python qaoa.py ... --ionq simulator                                # send the packed job to IonQ's cloud simulator
```

**IonQ key:** create a file named `.env` in the repo root with one line, `IONQ_API_KEY=<your key>`. `.env` is gitignored, so never commit the key. `qaoa.py` loads the file itself, so run it from the repo root; an `IONQ_API_KEY` environment variable works too. The packed circuit is compiled to IonQ's gate set before it is submitted. Run on the free `simulator` backend first, before spending credits on a `qpu.*` backend. On Qollab, press **Run** and pick the machine in **Select QPU**: Qollab injects its own `backend` (its IonQ key, your credits), `main.py` hands it to `qaoa.py`, and no `.env` is needed.

- **Encoding:** the QUBO's variables are each edge's use count, in binary, plus binary slack for the time budget. The cost is −score, plus `PENALTY` × (in − out)² at every node, plus `PENALTY` × (minutes + slack − budget)².
- **Scoring:** a bitstring counts as a route only if its edge counts equal a feasible route's (the key `quasar.search` uses). Routes are then scored exactly.
- **Self-check:** the run checks that the Qiskit circuit matches the NumPy simulation, and that the QUBO equals −score, up to a constant, on every route. Link climbs are included in the score. The QUBO check is skipped when a run or lift needs 3+ count bits, because there the QUBO only approximates "used at least once".
- **Help the baseline gets:** count bounds come from the same enumeration QWOA uses, which keeps the qubit count low. Without it, the QUBO would need even more qubits.

Measured with `qaoa.py`, 1,000 shots, with both circuits in one packed job on the local sampler:

| pod | budget | routes | qubits QWOA / QAOA | Aria MS gates at p=1 | P(optimal) p=1: QWOA / QAOA / random QAOA | P(optimal) p=2: QWOA / QAOA | QAOA shots that are routes (p=1) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Toy Lift A | 65 min | 16 | 4 / 16 | 34 / 240 | 0.368 / 0.006 / 0.006 | 0.516 / 0.006 | 4.5% |
| Crystal Quicksilver | 17 min | 3 | 2 / 15 | 7 / 210 | 0.502 / 0.006 / 0.008 | 0.512 / 0.003 | 3.1% |
| Crystal Gold Hills | 11 min | 4 | 2 / 14 | 4 / 182 | 0.999 / 0.012 / 0.016 | 1.000 / 0.014 | 2.4% |
| Crystal Discovery | 13 min | 6 | 3 / 18 | 24 / 306 | 0.896 / 0.001 / 0.001 | 0.999 / 0.002 | 0.5% |
| Crystal Green Valley | 14 min | 7 | 3 / 19 | 24 / 342 | 0.843 / 0.000 / 0.0005 | 1.000 / 0.000 | 1.1% |
| Crystal Gold Hills | 13 min | 7 | 3 / 20 | 24 / 380 | 0.631 / 0.001 / 0.0005 | 0.801 / 0.001 | 0.1% |

- **Qubits and gates:** the penalty QUBO needs 4–8× the qubits and 7–46× the two-qubit gates of QWOA on the same pod.
- **Wasted shots:** 95–99.9% of its shots aren't routes at all.
- **P(optimal):** at p=1 and p=2, QAOA's chance of the optimum stays at random-guess level. The angle optimizer minimizes expected cost, and the penalties dominate that cost, so the angles learn to avoid big violations rather than to find good routes.
- **Penalties don't separate routes from non-routes:** the cheapest non-route sits at most 1.5 best-scores above the optimum, and on Discovery and the 13-minute Gold Hills pod a non-route ties it. In both, the tying non-route is a subtour: the optimal route plus a detached loop (a run and a link back up to its start) that never touches the base. Flow penalties can't see subtours. On the toy pod, the cheapest non-route costs less than any route that scores under 78% of the best.
- This is the README's argument for QWOA, now measured: QWOA's mixer keeps every shot on a feasible route.
- **Caveat:** the comparison relies on the classical enumeration, so neither algorithm shows a speedup here.

**On IonQ's cloud simulator** (one job each, both circuits packed, p=1, 1,000 shots, on 2026-10-10):

| pod | qubits | IonQ job | optimum sampled, QWOA / QAOA | QAOA shots that aren't routes | same run, local sampler |
| --- | --- | --- | --- | --- | --- |
| Toy Lift A, 30 min | 14 | `01a127b5-4e08-74b1-b1c7-0b5a0401d869` | 362 / 26 | 845 | 385 / 21, 836 |
| Crystal Quicksilver, 17 min | 17 | `01a127b5-c03b-77c3-9eea-603be2344480` | 500 / 12 | 979 | 478 / 3, 981 |

IonQ's simulator agrees with the local sampler within shot noise. This also checks that `circuit.unpack` reads IonQ's bitstring counts correctly. These are cloud-simulator runs, not QPU runs; a hardware run is the next step (roadmap Milestone 2).

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

Planned work and milestones are in [docs/roadmap.md](docs/roadmap.md).

`main` only changes through pull requests. Every feature goes on its own branch (`feature/<name>`) and is merged through a pull request after CI passes. CI checks ruff lint and formatting (ruff pinned in `requirements.txt`), and runs the planner, beam search, QWOA and visualizer self-checks plus a small speedup analysis.

```sh
git switch main && git pull
git switch -c feature/<name>
# ...work...
python -m ruff format . && python -m ruff check .
git push -u origin feature/<name>   # then open a PR into main
```
