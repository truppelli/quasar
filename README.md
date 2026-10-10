# QUASAR — Quantitative Unique Alpine Ski Altitude Routing

Given where a skier is now and how much time they have, find a near-optimal route that gets the most vertical. No run is skied twice, and repeat lift rides cost points.

## Problem

We model a ski resort as a directed graph. Nodes are trail junctions and lift terminals. Runs give vertical drop and take time; lifts only take time. A **route** is a walk from the skier's current node to a finish node (by default the base) that fits inside their **time budget**.

```text
maximize   Σ vertical(runs)  −  LIFT_REPEAT_COST × (extra rides on the same lift)
subject to total minutes ≤ budget,  each run used at most once,  walk starts at `start` and ends at `end`
```

Because of the time budget, this is an orienteering / prize-collecting problem, which is NP-hard. We search the feasible routes with **QWOA**: QAOA whose mixer is a continuous-time quantum walk over the feasible routes ([Marsh & Wang 2020](https://arxiv.org/abs/1912.07353)). Every state the walk reaches is a valid route, so no probability is spent on invalid ones. With a penalty QUBO and the standard X mixer, only 2.9% of samples were valid. We report QWOA's results as **near-optimal** and compare them with the exact branch-and-bound optimum.

## Scale

| Instance (90 min budget) | Edges | Feasible routes \|F\| | B&B tree T | QWOA qubits ⌈log₂\|F\|⌉ |
| --- | --- | --- | --- | --- |
| Toy Peak | 9 | 46 | 1,440 | 6 |
| 1 lift pod | 7 | 29 | 848 | 5 |
| 3 lift pods | 23 | 8,104 | 5.4 × 10⁵ | 13 |
| 4 lift pods | 31 | 47,095 | 6.4 × 10⁶ | 16 |
| Large resort | ~200 | can't enumerate | ≫ 10¹³ (extrapolated) | — |

- The B&B tree grows by about 10^0.14 per extra lift or run. The budget sets the tree depth (budget ÷ shortest edge), so longer days also mean much bigger trees.
- Real mountains get split into lift pods. Each pod is solved separately, and the pieces are linked by traverses.
- **Near-term (IonQ):** run QWOA on single pods with a few hundred routes. The feasible routes are indexed classically, which is fine for validating the algorithm but gives no quantum advantage.

## Quantum speedup (large fault-tolerant machine)

`speedup.py` measures the size T of the classical branch-and-bound tree on growing synthetic resorts. It compares T with the cost of a quantum-walk search of the same tree:

- **Backtracking quantum walk** ([Montanaro 2018](https://arxiv.org/abs/1509.02374)) takes O(√T · n^1.5 · log n) steps, where n is the tree depth. For optimization, [Montanaro 2020](https://arxiv.org/abs/1906.10375) gives a near-quadratic speedup over branch-and-bound on every instance. This is the speedup we claim. It walks the tree with local moves, so it doesn't need the routes to be enumerated first.
- **Grover / Dürr–Høyer minimum finding** over all |F| routes takes √|F| steps versus |F|. This is the upper limit for the complete-graph QWOA mixer. QWOA itself has no proven speedup; it's a heuristic.

Measured with a 90-minute budget (`python speedup.py`):

| edges | B&B tree T | depth n | quantum steps | step speedup |
| --- | --- | --- | --- | --- |
| 7 | 848 | 13 | 5.1 × 10³ | 0.17× |
| 15 | 8.0 × 10⁴ | 15 | 6.4 × 10⁴ | 1.2× |
| 23 | 5.4 × 10⁵ | 16 | 1.9 × 10⁵ | 2.9× |
| 31 | 6.4 × 10⁶ | 17 | 7.3 × 10⁵ | 8.9× |
| 39 | 3.8 × 10⁷ | 19 | 2.2 × 10⁶ | 17.6× |

A step on an error-corrected machine is much slower than a classical step (`--overhead`, assumed to be 10⁴). Because of that, the quadratic speedup only shows up in wall-clock time once T > (overhead · n^1.5 · log n)² ≈ 10¹³ nodes. By extrapolation, that's a resort with roughly **60–100 lifts+runs**, depending on the fit. Large resorts are well past that size. The speedup is quadratic, not exponential, so the overhead matters a lot ([Babbush et al. 2021](https://arxiv.org/abs/2011.04149)).

## Run

```sh
pip install -r requirements.txt
python quasar.py --minutes 60                       # from the base
python quasar.py --start summit --minutes 25        # skier is at the summit
python quasar.py --minutes 90 --json                # plan only, for the app / visualizer
python speedup.py                                   # speedup table (~1 min)
```

## Visualizer

```sh
python serve.py    # then open http://localhost:8000
```

The visualizer draws the resort map: runs are solid blue lines and lifts are dashed grey. Click a junction, or use the dropdown, to set where the skier is, then set the minutes they have left. The near-optimal route appears in orange, with numbers showing the order. `serve.py` is a standard-library JSON API (`/resorts`, `/resort`, `/plan`) that the app can reuse.

## 3D mountain map

```sh
python serve.py    # then open http://localhost:8000/3d
```

Each resort is shown in 3D: satellite imagery and hillshade over terrain, with runs colored by difficulty (European colors for European resorts, North American colors elsewhere) and lifts as dashed lines. Click a run to see its elevation profile, length, vertical drop, and average and steepest pitch (the steepest is per 25 m elevation sample, so treat it as approximate). Mark a run 👍 or 👎, rate each skill level (Skip, Maybe or Want), then **Send feedback** to append the choices to `feedback.jsonl`. **Copy link** shares the current view, the runs you voted on and your skill-level choices.

Twenty popular US resorts, picked by approximate skier visits, are already included in `resorts/geo/`. They are cut from the [OpenSkiData](https://openskimap.org) dump in `data/openskidata/`:

```sh
python extract.py          # rebuild the 20 curated resorts (took 14 s on a laptop)
python extract.py --all    # every downhill ski area into data/geo/ (local only; served alongside the curated set)
```

## Resort data

Each resort is a file in `resorts/*.json`:

- `nodes`: `{name: [x, y, elevation_m]}`. x and y are map coordinates for the visualizer; use lon/lat for real resorts.
- `lifts` / `runs`: `[[name, from, to, minutes], ...]`. Run vertical is calculated from node elevations.
- `base`: the default start and finish node.

Add a mountain by adding a file. [OpenSkiMap](https://openskimap.org) has piste and lift data.

## Contributing

`main` only changes through pull requests. Every feature goes on its own branch (`feature/<name>`) and is merged through a pull request after CI passes. CI checks ruff lint and formatting, and runs the planner and QWOA self-checks and a small speedup analysis.

```sh
git switch main && git pull
git switch -c feature/<name>
# ...work...
python -m ruff format . && python -m ruff check .
git push -u origin feature/<name>   # then open a PR into main
```
