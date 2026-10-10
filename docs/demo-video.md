# Demo video outline (2–3 minutes)

The Qollab submission needs a 2–3 minute video at a public link (YouTube, Vimeo or Loom) that plays without signing in. Every number below comes from the README, so the video says the same thing the repo does.

## 1. The problem (0:00–0:30)

- **Show:** the 3D map (`python serve.py`, then `/3d`) flying to Stowe.
- **Say:** You have two hours at a big resort. Which lifts and runs give you the most new vertical? That's an orienteering problem, which is NP-hard. QUASAR plans it from wherever you're standing.

## 2. The classical planner (0:30–1:00)

- **Show:** on the 3D map, click the white dot at the top of Sensation Quad, set 2 h and press **Plan route**: an orange line with numbered steps from there back to the base, and the step list in the side panel. Slide to 1 h and let go to re-plan. Tip: scroll the side panel back up after planning, since a long step list pushes the controls out of view.
- **Say:** Pick where you are and how long you have. Exact branch-and-bound proves the best route on small resorts, and beam search plans a whole resort in a second or two. This classical planner is the baseline every quantum result is compared against.

## 3. QWOA on a lift pod (1:00–1:45)

- **Show:** `python quasar.py resorts/crystal-mountain-washington.json --pods`, then the Qollab project: press **Run** on IonQ's Forte Enterprise 1 noise-model simulator (free) and show the output. Then the README's IonQ table, including the Forte 1 hardware row if it's back.
- **Say:** We cut the resort into lift pods small enough for today's qubits. QWOA's mixer is a quantum walk over valid routes only, so every measurement is a real route. The textbook alternative is a penalty QUBO with the standard X mixer. On Crystal's Quicksilver pod it needs 15 qubits instead of 2 and 30 times the two-qubit gates. Both circuits go to IonQ in one job, because an IonQ run takes one circuit. On IonQ's noise model of Forte Enterprise 1, QWOA sampled the best route 485 times in 1,000 shots; the penalty QUBO found it 5 times, and 980 of its shots weren't routes at all. Across our pods QWOA's approximation ratio is 0.84 to 1.00, and the penalty QUBO's stays near zero.

## 4. What it does and doesn't show (1:45–2:30)

- **Show:** the speedup table in the README.
- **Say:** Near-term runs check that the algorithm works. They don't show a speedup, because the routes are indexed classically. The speedup we claim is a quadratic one for the backtracking quantum walk on a fault-tolerant machine, and it only pays off past roughly 100 lifts and runs, which every real resort here is.

## 5. Credits (2:30–2:50)

- **Show:** team card with Student Track, Quantum Impact, the Colorado School of Mines node, the repo link and the Qollab project link.
- **Say:** QUASAR is open source under the MIT license. This effort is supported by Qollab and IonQ.
