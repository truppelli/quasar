"""QUASAR: the ski route with the most vertical in the skier's time budget, starting where they stand.

A run scores its full vertical the first time and partial credit on repeats; repeat lift rides cost points.
Exact branch-and-bound finds the optimum on small resorts, beam search handles big ones, and QWOA (QAOA whose
mixer is a continuous-time quantum walk over feasible routes) searches the same routes.
"""

import argparse
import heapq
import json

import numpy as np
from scipy.optimize import minimize

# Per-user preference knobs. Repeats are needed on real resorts, where many trails funnel into a few run-outs
# back to the base. Partial credit keeps long days skiing once new runs run out, while new runs still win 2:1.
RUN_REPEAT_CREDIT = 0.5  # share of a run's vertical a repeat descent scores
LIFT_REPEAT_COST = 50  # metres of vertical one repeat ride of the same lift costs


def load(path):
    with open(path, encoding="utf-8") as f:
        return build(json.load(f))


def build(r):
    """Resort dict: nodes {name: [x, y, elevation_m]}, lifts/runs/links [[name, from, to, minutes], ...].

    Links are short walks/skates between trails: free to repeat, but any height they climb is subtracted, so
    skiing a dip and walking back up can't farm points."""
    nodes, edges = r["nodes"], []
    for kind in ("lift", "run", "link"):
        for name, u, v, mins in r.get(kind + "s", []):
            if u not in nodes or v not in nodes or mins <= 0:
                raise ValueError(f"{r.get('name')}: bad {kind} {name!r}")
            drop = nodes[u][2] - nodes[v][2] if kind == "run" else 0
            edges.append(
                {
                    "id": len(edges),
                    "name": name,
                    "kind": kind,
                    "from": u,
                    "to": v,
                    "minutes": mins,
                    "vertical": max(drop, 0),
                    "climb": max(nodes[v][2] - nodes[u][2], 0) if kind == "link" else 0,
                }
            )
    return {**r, "edges": edges}


def search(resort, start, end, minutes, prune=True, max_nodes=None):
    """DFS over partial routes from start. Returns ({edge-count tuple: (score, path)}, tree nodes visited, max depth).

    prune=True is exact branch-and-bound (keeps only what's needed for the optimum);
    prune=False enumerates every feasible route, i.e. the QWOA search space.
    max_nodes stops early with the best route so far (tree == max_nodes means it may not be optimal).
    """
    edges = resort["edges"]
    out, home, rate = _prep(edges, end)
    sols, counts, path = {}, [0] * len(edges), []
    best, tree, depth = -np.inf, 0, 0

    def dfs(node, left, score):
        nonlocal best, tree, depth
        if tree == max_nodes:
            return
        tree += 1
        depth = max(depth, len(path))
        if node == end:
            sols.setdefault(tuple(counts), (score, path[:]))
            best = max(best, score)
        if prune and score + left * rate <= best:
            return
        for i in out.get(node, []):
            e = edges[i]
            gain = _gain(edges, i, path, counts[i], left, home)
            if gain is None:
                continue
            counts[i] += 1
            path.append(i)
            dfs(e["to"], left - e["minutes"], score + gain)
            counts[i] -= 1
            path.pop()

    dfs(start, minutes, 0)
    return sols, tree, depth


def _prep(edges, end):
    """Outgoing edges per node (best m/min first), fastest minutes home to `end`, and a max m/min bound."""
    out = {}
    for i, e in enumerate(edges):
        out.setdefault(e["from"], []).append(i)
    for v in out.values():  # most vertical per minute first, so good routes turn up early
        v.sort(key=lambda i: -edges[i]["vertical"] / edges[i]["minutes"])
    # Fastest minutes to `end` from (node, arrived by link?), obeying the same no-two-links rule as _gain,
    # so "can still get home" is never optimistic. Dijkstra on reversed edges.
    into = {}
    for e in edges:
        into.setdefault(e["to"], []).append(e)
    home = {(end, False): 0, (end, True): 0}
    heap = [(0, end, False), (0, end, True)]
    while heap:
        d, n, by_link = heapq.heappop(heap)
        if d > home[(n, by_link)]:
            continue
        for e in into.get(n, []):
            if (e["kind"] == "link") != by_link:
                continue  # e must be the edge that arrives at n in this state
            for f in (False, True):  # how we arrived at e["from"]
                key = (e["from"], f)
                if not (f and by_link) and d + e["minutes"] < home.get(key, np.inf):
                    home[key] = d + e["minutes"]
                    heapq.heappush(heap, (home[key], e["from"], f))
    return out, home, max(e["vertical"] / e["minutes"] for e in edges)


def _gain(edges, i, path, times_used, left, home):
    """Score for taking edge i next, or None if not allowed (chained link, can't get home in time)."""
    e = edges[i]
    if e["kind"] == "link" and path and edges[path[-1]]["kind"] == "link":
        return None  # links bridge one gap; chaining them just walks in circles
    if e["minutes"] + home.get((e["to"], e["kind"] == "link"), np.inf) > left:
        return None
    if e["kind"] == "link":
        return -e["climb"]
    if not times_used:
        return e["vertical"]
    return {"run": RUN_REPEAT_CREDIT * e["vertical"], "lift": -LIFT_REPEAT_COST}[e["kind"]]


def beam(resort, start, end, minutes, width=500):
    """Heuristic for resorts too big for exact search: partial routes are bucketed by minutes used and only the
    `width` best-scoring ones per minute are extended, so routes are compared at equal elapsed time.

    ponytail: not monotone in `minutes` (a longer budget can score below a shorter one); wider beams or a local
    search pass over the result are the upgrade path.
    """
    edges = resort["edges"]
    out, home, _ = _prep(edges, end)
    best = (0, ()) if start == end else (-np.inf, None)
    buckets = {0: {(start, ()): (0, start, 0.0, ())}}  # minute -> {(node, trails used): (score, node, used, path)}
    for t in range(int(minutes) + 1):
        bucket, per_node = [], {}
        for st in sorted(buckets.pop(t, {}).values(), key=lambda st: -st[0]):
            # diversity: at most `per_node` routes per junction, so zero-gain dithering in one spot
            # (flat segments + walks) can't crowd out routes heading up a lift
            if per_node.get(st[1], 0) < 5:
                per_node[st[1]] = per_node.get(st[1], 0) + 1
                bucket.append(st)
                if len(bucket) == width:
                    break
        for score, node, used, path in bucket:
            for i in out.get(node, []):
                gain = _gain(edges, i, path, path.count(i), minutes - used, home)
                if gain is None:
                    continue
                e = edges[i]
                st = (score + gain, e["to"], used + e["minutes"], path + (i,))
                if e["to"] == end and st[0] > best[0]:
                    best = (st[0], st[3])
                slot = buckets.setdefault(max(int(st[2]), t + 1), {})
                key = (e["to"], frozenset(st[3]))  # same place, same trails: keep the better one
                if key not in slot or slot[key][0] < st[0]:
                    slot[key] = st
    return best if best[1] is not None else None


def describe(resort, score, path):
    legs = [resort["edges"][i] for i in path]
    return {
        "score": round(score, 1),
        "vertical_m": round(sum(e["vertical"] for e in legs), 1),  # everything skied, repeats included
        "minutes": round(sum(e["minutes"] for e in legs), 1),
        "route": legs,
    }


def plan(resort, start, minutes, end=None, max_nodes=300_000, exact_max_edges=60):
    """Best route (the app path): exact branch-and-bound on small graphs if it finishes within max_nodes,
    else beam search. Real resorts (hundreds of edges) go straight to beam search; exact never finishes there.

    None if `end` is unreachable in time. "optimal" says whether the route is proven best.
    """
    end = end or resort["base"]
    found, exact = [], False
    if len(resort["edges"]) <= exact_max_edges:
        sols, tree, _ = search(resort, start, end, minutes, max_nodes=max_nodes)
        found = [max(sols.values(), key=lambda s: s[0])] if sols else []
        exact = tree < max_nodes
    if not exact and (b := beam(resort, start, end, minutes)):
        found.append(b)
    if not found:
        return None
    return {**describe(resort, *max(found, key=lambda s: s[0])), "optimal": exact}


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
    print(f"  {plan_['vertical_m']:.0f} m vertical in {plan_['minutes']:.0f} min (score {plan_['score']:.0f})")
    names = [e["name"] for e in plan_["route"] if e["kind"] != "link"]
    print("  " + " > ".join(n for k, n in enumerate(names) if k == 0 or n != names[k - 1]))


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
    print(f"{r['name']}: {start} -> {end}, {a.minutes:g} min")
    print("classical branch-and-bound optimum:" if best["optimal"] else "beam search (too big to prove optimal):")
    show(best)
    if not best["optimal"]:
        print("(QWOA demo needs every route enumerated; run it on a small resort such as resorts/toy.json)")
        raise SystemExit

    b = beam(r, start, end, a.minutes)
    assert b and abs(b[0] - best["score"]) < 1e-6, f"beam search found {b and b[0]}, optimum is {best['score']}"
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
