"""QUASAR: the ski route with the most vertical in the skier's time budget, starting where they stand.

Runs are skied at most once; lifts may repeat at a cost. Exact classical branch-and-bound finds the optimum;
QWOA (QAOA whose mixer is a continuous-time quantum walk over feasible routes) searches the same routes.
"""

import argparse
import json

import numpy as np
from scipy.optimize import minimize

LIFT_REPEAT_COST = 100  # metres of vertical one repeat ride of the same lift costs; per-user preference knob


def load(path):
    with open(path) as f:
        return build(json.load(f))


def build(r):
    """Resort dict: nodes {name: [x, y, elevation_m]}, lifts/runs [[name, from, to, minutes], ...]."""
    nodes, edges = r["nodes"], []
    for kind in ("lift", "run"):
        for name, u, v, mins in r[kind + "s"]:
            if u not in nodes or v not in nodes or mins <= 0:
                raise ValueError(f"{r.get('name')}: bad {kind} {name!r}")
            drop = nodes[u][2] - nodes[v][2] if kind == "run" else 0
            edges.append({"name": name, "kind": kind, "from": u, "to": v, "minutes": mins, "vertical": max(drop, 0)})
    return {**r, "edges": edges}


def search(resort, start, end, minutes, prune=True):
    """DFS over partial routes from start. Returns ({edge-count tuple: (score, path)}, tree nodes visited, max depth).

    prune=True is exact branch-and-bound (keeps only what's needed for the optimum);
    prune=False enumerates every feasible route, i.e. the QWOA search space.
    """
    edges = resort["edges"]
    out = {}
    for i, e in enumerate(edges):
        out.setdefault(e["from"], []).append(i)
    rate = max(e["vertical"] / e["minutes"] for e in edges)  # upper bound on metres per minute
    sols, counts, path = {}, [0] * len(edges), []
    best, tree, depth = -np.inf, 0, 0

    def dfs(node, left, score):
        nonlocal best, tree, depth
        tree += 1
        depth = max(depth, len(path))
        if node == end:
            sols.setdefault(tuple(counts), (score, path[:]))
            best = max(best, score)
        if prune and score + left * rate <= best:
            return
        for i in out.get(node, []):
            e = edges[i]
            if e["minutes"] > left or (e["kind"] == "run" and counts[i]):
                continue
            gain = e["vertical"] if e["kind"] == "run" else -LIFT_REPEAT_COST * (counts[i] > 0)
            counts[i] += 1
            path.append(i)
            dfs(e["to"], left - e["minutes"], score + gain)
            counts[i] -= 1
            path.pop()

    dfs(start, minutes, 0)
    return sols, tree, depth


def describe(resort, score, path):
    legs = [resort["edges"][i] for i in path]
    return {
        "score": score,
        "vertical_m": sum(e["vertical"] for e in legs),
        "minutes": sum(e["minutes"] for e in legs),
        "route": legs,
    }


def plan(resort, start, minutes, end=None):
    """Exact optimal route via branch-and-bound (the app path). None if `end` is unreachable in time."""
    sols, _, _ = search(resort, start, end or resort["base"], minutes)
    return describe(resort, *max(sols.values(), key=lambda s: s[0])) if sols else None


def qwoa(scores, p=3, restarts=5, seed=0):
    """QAOA over feasible routes only, mixer = continuous-time quantum walk on the complete graph (Marsh & Wang 2020).

    Returns the final measurement probability of each route.
    ponytail: routes are indexed by classical enumeration, fine for simulation; hardware needs an indexing
    unitary over feasible routes, or the backtracking quantum walk analysed in speedup.py.
    """
    C = -np.asarray(scores, float)
    C /= np.abs(C).max() or 1
    M = len(C)

    def state(th):
        psi = np.full(M, M**-0.5, dtype=complex)
        for g, b in zip(th[:p], th[p:]):
            psi = psi * np.exp(-1j * g * C)
            psi = psi + (np.exp(-1j * b * M) - 1) * psi.mean()  # exp(-i b A), A = complete-graph adjacency
        return psi

    rng = np.random.default_rng(seed)
    f = lambda th: float(np.abs(state(th)) ** 2 @ C)
    starts = (np.r_[rng.uniform(0, np.pi, p), rng.uniform(0, 2 * np.pi / M, p)] for _ in range(restarts))
    best = min((minimize(f, x0, method="COBYLA") for x0 in starts), key=lambda r: r.fun)
    return np.abs(state(best.x)) ** 2


def show(plan_):
    print(f"  {plan_['vertical_m']} m vertical in {plan_['minutes']} min (score {plan_['score']})")
    print("  " + " > ".join(e["name"] for e in plan_["route"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("resort", nargs="?", default="resorts/toy.json")
    ap.add_argument("--minutes", type=float, default=60, help="time the skier has left")
    ap.add_argument("--start", help="node the skier is at now (default: resort base)")
    ap.add_argument("--end", help="node to finish at (default: resort base)")
    ap.add_argument("--json", action="store_true", help="print only the optimal plan as JSON (for the app)")
    a = ap.parse_args()

    r = load(a.resort)
    start, end = a.start or r["base"], a.end or r["base"]
    for n in (start, end):
        if n not in r["nodes"]:
            ap.error(f"unknown node {n!r}; choose from {sorted(r['nodes'])}")
    best = plan(r, start, a.minutes, end)
    if a.json:
        print(json.dumps(best))
        raise SystemExit
    if best is None:
        raise SystemExit(f"can't get from {start} to {end} in {a.minutes} min")
    print(f"{r['name']}: {start} -> {end}, {a.minutes} min")
    print("classical branch-and-bound optimum:")
    show(best)

    sols, _, _ = search(r, start, end, a.minutes, prune=False)
    routes = list(sols.values())
    scores = np.array([s for s, _ in routes])
    assert scores.max() == best["score"], "branch-and-bound pruned away the optimum"

    probs = qwoa(scores)
    opt = scores == scores.max()
    top = routes[int(probs.argmax())]
    print(
        f"QWOA over {len(routes)} feasible routes (p=3): P(optimal) = {probs[opt].sum():.3f}"
        f" vs {opt.mean():.3f} random, expected score {probs @ scores:.0f} of {scores.max()}"
    )
    print("most likely route:")
    show(describe(r, *top))
    assert opt.all() or probs[opt].sum() > opt.mean(), "QWOA did no better than random guessing"
