# Contributions

## Kevin ([@MACKAYConcept](https://github.com/MACKAYConcept)), co-author

Kevin built the team's Qollab hackathon prototype in [MACKAYConcept/Qollab-Hackathon](https://github.com/MACKAYConcept/Qollab-Hackathon). That code was ported into this repo without its git history. What came across:

- **One job per IonQ run.** Qollab's IonQ backends accept one circuit per run, so the prototype packed several circuits onto disjoint qubits of one circuit and split the counts afterwards. This is now `circuit.pack` / `circuit.unpack`, used by `qaoa.py` to send QWOA and its baseline in one job.
- **Penalty-QUBO QAOA.** The prototype's QAOA (QUBO cost, Ising Z/ZZ rotations, X mixer) is the basis of `qaoa.py`, the baseline QWOA is compared against. It was rewritten so the bitstrings encode routes on a lift pod (edge use counts with flow-conservation and time-budget penalties), and so sampled bitstrings are checked against the exact feasible routes and scored exactly.
- **Hackathon framing.** The Qollab submission details (Student Track, Quantum Impact theme, Colorado School of Mines node, Qollab & IonQ attribution), the root `main.py` entry point for the Qollab platform, and the demo video outline in `docs/demo-video.md`.

Not ported: the hand-built Winter Park GeoJSON (`resorts/winter-park.json` is built from OpenSkiMap), the CTQW node-pruning step, and the greedy and simulated-annealing baselines and their charts. Those depended on the prototype's edge-subset QUBO rather than on routes. The prototype was developed with AI pair-programming assistance from Google Antigravity.

## Phillip Truppelli

Planner, QWOA, resort data pipeline, visualizers and API: the rest of the repo.
