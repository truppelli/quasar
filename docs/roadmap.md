# QUASAR roadmap

Where QUASAR is today, what the next milestones are, and the direction behind them. Milestones are in priority order. Each one should ship as one or more `feature/<name>` PRs into `main`.

## Where we are

| Area | State on `main` |
| --- | --- |
| Planner (`quasar.py`) | Exact branch-and-bound for small resorts and beam search for big ones (`optimal: false`). Unique-vertical objective with repeat penalties. |
| Quantum (`quasar.py`, `speedup.py`) | QWOA simulated in NumPy over classically enumerated routes. Speedup analysis for the backtracking quantum walk (a quadratic speedup, which needs about 100+ lifts and runs before it pays off in wall-clock time). |
| Real resort graphs (`datasets.py`) | Crystal Mountain WA and Whistler Blackcomb, built from OpenSkiMap and Global Ski Atlas. |
| 2D visualizer (`viz.html`, `/`) | Plans and draws a route on any resort graph. |
| 3D map (`map3d.html`, `/3d`) | 20 US resorts in 3D. Run inspector, 👍/👎 per run, per-level interest, feedback saved to `feedback.jsonl`, shareable links. |
| API (`serve.py`) | Stdlib server: `/resorts`, `/resort`, `/plan`, `/geo`, `POST /feedback`. |

In progress on `feature/repeat-scoring`: half credit for repeat runs so that long budgets fill the day.

**The main gap:** the planner and the 3D map don't share any resorts yet. The map has 20 US resorts with geometry, the planner has 2 resorts with graphs, and none are in both. Milestone 1 closes that gap.

## Milestone 1: Plan your day on the 3D map

This is the core product: a skier sees the mountain, says what they like, and gets a route.

- **One data pipeline.** Merge `extract.py` and `datasets.py` into a single build that streams OpenSkiData once per resort and writes both the planner graph (`resorts/<slug>.json`) and the map geometry (`resorts/geo/<slug>.geojson`), with the same slugs and the same run ids. Build graphs for all 20 curated resorts.
- **Route on the 3D map.** Call `/plan` from `map3d.html` and draw the route as an orange line with numbered steps, along with its score, minutes and `optimal` flag. Show the route list in the side panel.
- **Start where you are.** Click a lift terminal or junction on the 3D map to set the start node. Add a minutes slider.
- **Preference-aware planning.** Add `exclude=` (run ids) and `levels=` to `/plan` and `quasar.plan`. 👎 runs and "Skip" levels are excluded, and "Want" levels get a score bonus. This is the first place feedback changes the result.
- **Retire or merge the 2D visualizer** once the 3D map does everything it does. Keep one map.

**Done when:** for any of the 20 resorts, a skier can pick a start, set a time, mark their preferences, and see a route that respects them, from a shared link.

## Milestone 2: QWOA on IonQ hardware

Validate the quantum algorithm on real hardware with honest claims.

- **Lift-pod decomposition** *(done: `quasar.py --pods` / `--pod`)*. Split a resort into pods (one lift plus the runs it serves) and solve each pod separately, linked by traverses. The pods are small enough to enumerate (a few hundred routes, roughly 6–10 qubits).
- **Qiskit circuit for QWOA** *(done: `circuit.py`; first hardware target is 4 qubits, p=1, about 34–55 MS gates)*. Port the NumPy QWOA to a Qiskit circuit: a phase separator over route indices, plus a complete-graph walk mixer, which is a Grover-style diffusion over the feasible-route register. Run it on a simulator first, then on IonQ through the `qiskit-ionq` provider.
- **Benchmark against exact.** For each pod, report the probability of sampling the optimum, the approximation ratio and the shot count, compared with branch-and-bound. Publish the table in the README next to the speedup analysis.
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

- Which pods make the best first hardware run: the smallest real pod, or a synthetic pod with a known optimum?
- Should the curated set grow past 20 US resorts before the beta, or should the `--all` set be served via PMTiles instead?
- How much should feedback reshape a route compared with pure vertical? This needs data from Milestone 5 to tune.
