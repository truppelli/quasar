# QUASAR roadmap

Where QUASAR is today, what the next milestones are, and the direction behind them. Milestones are in priority order. Each one should ship as one or more `feature/<name>` PRs into `main`.

## Where we are

| Area | State on `main` |
| --- | --- |
| Planner (`quasar.py`) | Exact branch-and-bound for small resorts and beam search for big ones (`optimal: false`). Unique-vertical objective with repeat penalties. |
| Quantum (`quasar.py`, `circuit.py`, `qaoa.py`, `speedup.py`) | QWOA simulated in NumPy over classically enumerated routes, plus as a Qiskit circuit. Penalty-QUBO QAOA baseline, with both circuits packed into one IonQ job. Speedup analysis for the backtracking quantum walk (a quadratic speedup, which needs about 100+ lifts and runs before it pays off in wall-clock time). |
| Qollab (`main.py`) | Qollab's Run button runs `main.py` on the machine picked in Select QPU: Crystal Quicksilver, 17 qubits, one job. Checked on Qollab's local simulator and IonQ's Forte Enterprise 1 noise-model simulator; the first QPU job is queued on Forte 1. A dropped connection while a job waits is retried, and `JOB_ID` in `main.py` fetches an earlier job without paying again. |
| Real resort graphs (`datasets.py`) | The 3D map's 20 US resorts (`datasets.py --top-us`, same slugs as the map), plus Crystal Mountain WA and Whistler Blackcomb, built from OpenSkiMap and Global Ski Atlas. Repeat runs score half credit, so long budgets fill the day. |
| 2D visualizer (`viz.html`, `/`) | Plans and draws a route on any resort graph. |
| 3D map (`map3d.html`, `/3d`) | 20 US resorts in 3D. Run inspector, 👍/👎 per run, per-level interest, feedback saved to `feedback.jsonl`, shareable links. |
| API (`serve.py`) | Stdlib server: `/resorts`, `/resort`, `/plan`, `/geo`, `POST /feedback`. |

**The main gap:** the planner and the 3D map now cover the same 20 resorts, but the map can't show a route yet. The graphs name runs by trail name while the map's geometry uses OpenSkiMap ids, so nothing links a planned run to its shape on the map. Milestone 1 closes that gap.

## Milestone 1: Plan your day on the 3D map

This is the core product: a skier sees the mountain, says what they like, and gets a route.

- **One data pipeline** *(graphs for all 20 curated resorts done, with the map's slugs)*. Merge `extract.py` and `datasets.py` into a single build that streams OpenSkiData once per resort and writes both the planner graph (`resorts/<slug>.json`) and the map geometry (`resorts/geo/<slug>.geojson`) with the same run ids.
- **Route on the 3D map** *(done: "Plan my day" in `map3d.html`; the route follows the map's own run and lift lines where names match, about 9 in 10 legs, straight lines elsewhere; `min=` in the link replays it)*. Call `/plan` from `map3d.html` and draw the route as an orange line with numbered steps, along with its score, minutes and `optimal` flag. Show the route list in the side panel. This doesn't have to wait for shared run ids: graph nodes store x/y metres from the resort's `origin_lonlat`, so the line can be drawn from the nodes.
- **Start where you are** *(done: click a white lift dot to start at the nearest junction, Base to reset; minutes slider; `start=` in the link)*. Click a lift terminal or junction on the 3D map to set the start node. Add a minutes slider.
- **Preference-aware planning.** Add `exclude=` (run ids) and `levels=` to `/plan` and `quasar.plan`. 👎 runs and "Skip" levels are excluded, and "Want" levels get a score bonus. This is the first place feedback changes the result.
- **Retire or merge the 2D visualizer** once the 3D map does everything it does. Keep one map.

**Done when:** for any of the 20 resorts, a skier can pick a start, set a time, mark their preferences, and see a route that respects them, from a shared link.

## Milestone 2: QWOA on IonQ hardware

Validate the quantum algorithm on real hardware with honest claims.

- **Lift-pod decomposition** *(done: `quasar.py --pods` / `--pod`)*. Split a resort into pods (one lift plus the runs it serves) and solve each pod separately, linked by traverses. The pods are small enough to enumerate (a few hundred routes, roughly 6–10 qubits).
- **Qiskit circuit for QWOA** *(done: `circuit.py`; ran on IonQ's cloud simulator via `qaoa.py --ionq simulator`; first hardware run is Crystal Quicksilver: 2 QWOA qubits, p=1, 7 MS gates)*. Port the NumPy QWOA to a Qiskit circuit: a phase separator over route indices, plus a complete-graph walk mixer, which is a Grover-style diffusion over the feasible-route register. Run it on a simulator first, then on IonQ through the `qiskit-ionq` provider.
- **Benchmark against exact** *(done: P(optimal), approximation ratio and shots in `qaoa.py` and the README's baseline table)*. For each pod, report the probability of sampling the optimum, the approximation ratio and the shot count, compared with branch-and-bound. Publish the table in the README next to the speedup analysis.
- **Penalty-QUBO baseline** *(done: `qaoa.py`)*. Run standard X-mixer QAOA on the same pod. It needs 4–8× the qubits, and nearly all of its shots aren't routes.
- **Hardware run** *(in progress)*. Crystal Quicksilver (17 min, 3 routes; 2 QWOA + 15 QAOA qubits, one packed job, 1,000 shots) queued through Qollab on IonQ Forte 1 (job `01a1281a-4614-78ed-bc86-1a60b5c18f9b`). Aria 1 is retired, so Forte is the target. The same job on IonQ's Forte Enterprise 1 noise model sampled the optimum 485 times by QWOA and 5 by QAOA. Its results go in the README next to the simulator runs.
- **Batch, not interactive.** Hardware runs are offline jobs whose results are cached and served. `/plan` stays classical so the app is fast.
- **Be clear what this proves.** Route indexing is classical, so this validates QWOA rather than demonstrating any speedup. The README's speedup argument (backtracking walk, fault-tolerant scale) stays separate.

**Done when:** at least one real-resort pod has been run on IonQ hardware, and its results are compared with the exact optimum in the README.

## Milestone 3: Planner quality

Make the classical routes good enough to trust, because they're the baseline every quantum result is compared against.

- **Beam search monotonicity.** A longer budget can currently score lower (`ponytail:` in `quasar.beam`). Add a local-search pass over the beam's result (2-opt or swap a lap), or widen the beam adaptively.
- **Calibrate against reality.** Compare lift wait, skiing speed and walk speed (the knobs at the top of `datasets.py`) with skiers' reported times, and expose per-skier speed as a plan parameter.
- **Data fixes:**
  - include area-shaped runs (bowls as polygons), which are currently skipped;
  - check run direction where the map data's point order is wrong;
  - stop assuming "Express" chairs are detachable.
- **Regression set.** Pin a handful of (resort, start, minutes) cases with known scores in CI, so planner changes can't silently get worse.

## Milestone 4: Public beta

Put it in front of real skiers. The architecture below comes from the architecture session's design.

- **Hosting:** the map pages are static files on a CDN. The `serve.py` endpoints run in a single Python container, with `/plan` in a process pool with a timeout and a cache.
- **Data:** an offline pipeline (from Milestone 1) writes per-resort JSON plus vector tiles (PMTiles) to object storage. This replaces per-request GeoJSON and makes the `--all` resort set servable.
- **Feedback store:** move from `feedback.jsonl` to SQLite with Litestream backups. The record shape stays the same.
- **Licensing:** check Esri World Imagery's terms for public use, or switch providers. The basemap is a single URL in `map3d.html`. Keep OpenSkiMap/OSM and terrain attribution.
- **Abuse limits:** rate-limit `POST /feedback` and `/plan` per IP. There are no accounts in the beta.
- **Domain:** pick a skier-facing name. The acronym can stay for the research write-up.

## Milestone 5: Close the feedback loop

Use what skiers tell us.

- **Feedback dashboard:** most-wanted runs and skill-level mix per resort, built from the feedback store.
- **Personal scoring:** turn level interest and 👍/👎 history into per-skier score weights, so "Want" levels are worth more and "Skip" levels are excluded.
- **Group trips:** combine several skiers' preferences into one shared route, or split routes that meet up for lunch.
- **Live conditions (stretch):** lift status and grooming reports from resort feeds, so closed lifts drop out of the graph.

## Not planned

- Accounts and logins, until the beta shows people come back.
- Claiming a near-term quantum advantage. Near-term hardware runs are for validation, and the speedup claim is the fault-tolerant analysis in the README.
- A native mobile app. The 3D map is responsive and works in mobile browsers.

## Open questions

- Should the curated set grow past 20 US resorts before the beta, or should the `--all` set be served via PMTiles instead?
- How much should feedback reshape a route compared with pure vertical? This needs data from Milestone 5 to tune.
