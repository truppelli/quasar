"""QUASAR: the ski route with the most vertical in the skier's time budget, starting where they stand.

A run scores its full vertical the first time and partial credit on repeats; repeat lift rides cost points.
Exact branch-and-bound finds the optimum on small resorts, beam search handles big ones, and QWOA (QAOA whose
mixer is a continuous-time quantum walk over feasible routes) searches the same routes.
"""

import argparse
import heapq
import json
import math
import sys

import numpy as np
from scipy.optimize import minimize

# Per-user preference knobs. Repeats are needed on real resorts, where many trails funnel into a few run-outs
# back to the base. Partial credit keeps long days skiing once new runs run out, while new runs still win 2:1.
RUN_REPEAT_CREDIT = 0.5  # share of a run's vertical a repeat descent scores
LIFT_REPEAT_COST = 50  # metres of vertical one repeat ride of the same lift costs
WANT_BONUS = 0.5  # a run the skier wants scores this share of its vertical extra (plan(want=...))


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
        v.sort(key=lambda i: -_value(edges[i]) / edges[i]["minutes"])
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
    return out, home, max(_value(e) / e["minutes"] for e in edges)


def _value(e):
    """What an edge's first descent scores: its vertical, or more for a run the skier wants (plan(want=...))."""
    return e.get("value", e["vertical"])


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
        return _value(e)
    return {"run": RUN_REPEAT_CREDIT * _value(e), "lift": -LIFT_REPEAT_COST}[e["kind"]]


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


def plan(resort, start, minutes, end=None, max_nodes=None, exclude=(), want=()):
    """Best route (the app path): exact branch-and-bound if it finishes within max_nodes, else beam search.

    Default cap: 300k nodes on small graphs (<= 60 edges), 20k on bigger ones. Lift pods finish well inside 20k;
    whole resorts never finish, so they only lose a fraction of a second before beam search.
    None if `end` is unreachable in time. "optimal" says whether the route is proven best.
    exclude: run edge ids the skier won't ski (dropped from the graph); want: run edge ids worth WANT_BONUS extra.
    """
    if exclude or want:
        exclude, want = set(exclude), set(want)
        edges = [
            {**e, "value": e["vertical"] * (1 + WANT_BONUS)} if e["id"] in want else e
            for e in resort["edges"]
            if not (e["kind"] == "run" and e["id"] in exclude)
        ]
        resort = {**resort, "edges": edges}
    end = end or resort["base"]
    max_nodes = max_nodes or (300_000 if len(resort["edges"]) <= 60 else 20_000)
    sols, tree, _ = search(resort, start, end, minutes, max_nodes=max_nodes)
    found = [max(sols.values(), key=lambda s: s[0])] if sols else []
    exact = tree < max_nodes
    if not exact and (b := beam(resort, start, end, minutes)):
        found.append(b)
    if not found:
        return None
    return {**describe(resort, *max(found, key=lambda s: s[0])), "optimal": exact}


POD_BAND_M = 20  # a pod's trails stay within its lift's bottom-to-top elevation, give or take this much


def pods(resort):
    """Split a resort into lift pods: one lift plus the runs and links that lead from its top back to its bottom
    without another lift or leaving the lift's elevation band. Each pod is a resort dict (base = lift bottom).

    Pods are small instances for QWOA on hardware. They can overlap, so they don't tile the resort.
    ponytail: no pod-to-pod linking yet; whole-day plans still use plan() on the full resort.
    """
    z = {n: xyz[2] for n, xyz in resort["nodes"].items()}
    for lift in (e for e in resort["edges"] if e["kind"] == "lift"):
        lo, hi = z[lift["from"]] - POD_BAND_M, z[lift["to"]] + POD_BAND_M
        down = [
            e for e in resort["edges"] if e["kind"] != "lift" and lo <= z[e["from"]] <= hi and lo <= z[e["to"]] <= hi
        ]
        keep = _reach(down, lift["to"], "from", "to") & _reach(down, lift["from"], "to", "from")
        legs = [e for e in down if e["from"] in keep and e["to"] in keep]
        if not any(e["kind"] == "run" for e in legs):
            continue  # a traverse lift: nothing skis back to its own bottom
        rows = {
            k: [[e["name"], e["from"], e["to"], e["minutes"]] for e in legs if e["kind"] == k] for k in ("run", "link")
        }
        yield build(
            {
                "name": f"{resort['name']}: {lift['name']}",
                "lift": lift["name"],
                "base": lift["from"],
                "nodes": {n: resort["nodes"][n] for n in keep | {lift["from"], lift["to"]}},
                "lifts": [[lift["name"], lift["from"], lift["to"], lift["minutes"]]],
                "runs": rows["run"],
                "links": rows["link"],
            }
        )


def _reach(edges, start, a, b):
    """Nodes reachable from start following edges a -> b (pass "to", "from" to walk them backwards)."""
    adj = {}
    for e in edges:
        adj.setdefault(e[a], []).append(e[b])
    seen, todo = {start}, [start]
    while todo:
        for n in adj.get(todo.pop(), []):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


def pod_budget(pod, max_routes=512, max_minutes=120, max_nodes=50_000):
    """Longest whole-minute budget, from one lap up, whose feasible routes number at most max_routes
    (so they index into ceil(log2(max_routes)) qubits). Returns (minutes, routes), or None if one lap is too many.
    """
    lift = pod["edges"][0]  # build() puts lifts first and a pod has one
    _, home, _ = _prep(pod["edges"], pod["base"])
    best = None
    for m in range(int(np.ceil(lift["minutes"] + home.get((lift["to"], False), np.inf))), max_minutes + 1):
        sols, tree, _ = search(pod, pod["base"], pod["base"], m, prune=False, max_nodes=max_nodes)
        if tree == max_nodes or len(sols) > max_routes:
            break
        best = (m, len(sols))
    return best


def qwoa(scores, p=3, restarts=5, seed=0):
    """QAOA over feasible routes only, mixer = continuous-time quantum walk on the complete graph (Marsh & Wang 2020).

    Returns the final measurement probability of each route and the optimized angles.
    ponytail: routes are indexed by classical enumeration, fine for simulation; hardware needs an indexing
    unitary over feasible routes, or the backtracking quantum walk analysed in speedup.py.
    """
    C = qwoa_cost(scores)
    M = len(C)
    rng = np.random.default_rng(seed)
    f = lambda th: float(np.abs(qwoa_state(C, th)) ** 2 @ C)
    starts = (np.r_[rng.uniform(0, np.pi, p), rng.uniform(0, 2 * np.pi / M, p)] for _ in range(restarts))
    best = min((minimize(f, x0, method="COBYLA") for x0 in starts), key=lambda r: r.fun)
    return np.abs(qwoa_state(C, best.x)) ** 2, best.x


def qwoa_cost(scores):
    """QWOA cost per route: minus the score, scaled to [-1, 1] so the angles don't depend on units."""
    C = -np.asarray(scores, float)
    return C / (np.abs(C).max() or 1)


def qwoa_state(C, theta):
    """Final QWOA amplitudes over routes; theta = p phase angles then p walk angles."""
    p, M = len(theta) // 2, len(C)
    psi = np.full(M, M**-0.5, dtype=complex)
    for g, b in zip(theta[:p], theta[p:]):
        psi = psi * np.exp(-1j * g * C)
        psi = psi + (np.exp(-1j * b * M) - 1) * psi.mean()  # exp(-i b A), A = complete-graph adjacency
    return psi


def show(plan_):
    print(f"  {plan_['vertical_m']:.0f} m vertical in {plan_['minutes']:.0f} min (score {plan_['score']:.0f})")
    names = [e["name"] for e in plan_["route"] if e["kind"] != "link"]
    print("  " + " > ".join(n for k, n in enumerate(names) if k == 0 or n != names[k - 1]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("resort", nargs="?", default="resorts/toy.json")
    ap.add_argument("--minutes", type=float, help="time the skier has left (default 60, or the pod's budget)")
    ap.add_argument("--start", help="node the skier is at now (default: resort base)")
    ap.add_argument("--end", help="node to finish at (default: resort base)")
    ap.add_argument("--json", action="store_true", help="print only the optimal plan as JSON (for the app)")
    ap.add_argument("--pods", action="store_true", help="list the resort's lift pods and their QWOA sizes")
    ap.add_argument("--pod", metavar="LIFT", help="plan + QWOA on one lift pod instead of the whole resort")
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # lift names like "Sq̓útsa" crash a Windows console otherwise

    toy = {p["lift"]: sorted(e["name"] for e in p["edges"][1:]) for p in pods(load("resorts/toy.json"))}
    assert toy == {"Lift A": ["Mid Cruiser", "Mid Steeps"], "Lift B": ["Summit Glades"], "Lift C": ["Ridge Run"]}, toy

    r = load(a.resort)
    if a.pods:
        print(f"{r['name']}: lift pods (QWOA budget = most minutes with <= 512 routes, i.e. <= 9 qubits)")
        for p in pods(r):
            size = pod_budget(p)
            runs = sum(e["kind"] == "run" for e in p["edges"])
            fit = f"{size[0]:>3} min {size[1]:>4} routes {math.ceil(math.log2(size[1]))} qubits" if size else "too big"
            print(f"  {p['lift'][:32]:32} {runs:>3} runs  {fit}")
        raise SystemExit
    if a.pod:
        r = next((p for p in pods(r) if p["lift"] == a.pod), None) or ap.error(f"no pod for lift {a.pod!r}; see --pods")
        a.minutes = a.minutes or (pod_budget(r) or ap.error(f"{a.pod} pod is too big for QWOA"))[0]
    a.minutes = a.minutes or 60
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
    assert b and b[0] < best["score"] + 0.1, f"beam search beat the optimum: {b and b[0]} > {best['score']}"
    if best["score"] > 0:
        print(f"beam search (heuristic) on the same instance: score {b[0]:.0f}, {b[0] / best['score']:.1%} of optimal")
    sols, _, _ = search(r, start, end, a.minutes, prune=False)
    routes = list(sols.values())
    scores = np.array([s for s, _ in routes])
    assert abs(scores.max() - best["score"]) < 0.1, "branch-and-bound pruned away the optimum"  # plan() rounds

    probs, _ = qwoa(scores)
    opt = scores == scores.max()
    top = routes[int(probs.argmax())]
    print(
        f"QWOA over {len(routes)} feasible routes (p=3): P(optimal) = {probs[opt].sum():.3f}"
        f" vs {opt.mean():.3f} random, expected score {probs @ scores:.0f} of {scores.max():.0f}"
    )
    print("most likely route:")
    show(describe(r, *top))
    assert opt.all() or probs[opt].sum() > opt.mean(), "QWOA did no better than random guessing"
