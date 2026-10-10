# Demo video outline (2–3 minutes)

The Qollab submission needs a 2–3 minute video at a public link (YouTube, Vimeo or Loom) that plays without signing in. Every number below comes from the README, so the video says the same thing the repo does.

## 1. The problem (0:00–0:30)

- **Show:** the 3D map (`python serve.py`, then `/3d`) flying to Crystal Mountain.
- **Say:** You have two hours at a big resort. Which lifts and runs give you the most new vertical? That's an orienteering problem, which is NP-hard. QUASAR plans it from wherever you're standing.

## 2. The classical planner (0:30–1:00)

- **Show:** the 2D visualizer drawing a route; `python quasar.py resorts/whistler-blackcomb.json --minutes 120`.
- **Say:** Exact branch-and-bound proves the best route on small resorts. Beam search plans a whole resort in seconds. This is the baseline every quantum result is compared against.

## 3. QWOA on a lift pod (1:00–1:45)

- **Show:** `python quasar.py resorts/crystal-mountain-washington.json --pods`, then `python main.py resorts/crystal-mountain-washington.json --pod "Quicksilver" --max-routes 4`.
- **Say:** We cut the resort into lift pods small enough for today's qubits. QWOA's mixer is a quantum walk over valid routes only, so every measurement is a real route. The textbook alternative is a penalty QUBO with the standard X mixer. On the same pod it needs about 15 qubits instead of 2 and about 30 times the two-qubit gates, and most of its shots aren't routes at all. Both circuits go to IonQ in one job, because an IonQ run takes one circuit.

## 4. What it does and doesn't show (1:45–2:30)

- **Show:** the speedup table in the README.
- **Say:** Near-term runs check that the algorithm works. They don't show a speedup, because the routes are indexed classically. The speedup we claim is a quadratic one for the backtracking quantum walk on a fault-tolerant machine, and it only pays off past roughly 100 lifts and runs, which every real resort here is.

## 5. Credits (2:30–2:50)

- **Show:** team card with Student Track, Quantum Impact, the Colorado School of Mines node, the repo link and the Qollab project link.
- **Say:** QUASAR is open source under the MIT license. This effort is supported by Qollab and IonQ.
