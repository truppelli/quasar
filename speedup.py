"""Estimate QUASAR's quantum-walk speedup on a large fault-tolerant quantum computer.

Classical cost: T = nodes visited by exact branch-and-bound (quasar.search). Quantum cost: Montanaro's quantum-walk
backtracking runs the same tree in O(sqrt(T) * n^1.5 * log n) steps (n = tree depth); his 2020 branch-and-bound
result gives the same near-quadratic speedup for optimisation. Also shown: Grover/Durr-Hoyer minimum finding
over all |F| feasible routes, sqrt(|F|) vs |F|, which bounds what the complete-graph QWOA mixer can achieve.

Counts are steps, not seconds. Each error-corrected quantum step is assumed --overhead times slower than a
classical node visit, so the quantum walk only wins once T > (overhead * n^1.5 * log n)^2.
"""

import argparse

import numpy as np

import quasar


def synthetic(zones, seed=0):
    """Resort with `zones` lift pods off one base, each pod linked to the next by a traverse."""
    rng = np.random.default_rng(seed)
    nodes, lifts, runs = {"base": [0, 0, 2000]}, [], []
    for k in range(zones):
        mid, top = f"mid{k}", f"top{k}"
        nodes[mid] = [k, 1, 2000 + rng.integers(300, 600)]
        nodes[top] = [k, 2, nodes[mid][2] + rng.integers(200, 500)]
        lifts += [[f"L{k}a", "base", mid, int(rng.integers(6, 11))], [f"L{k}b", mid, top, int(rng.integers(5, 9))]]
        runs += [
            [f"R{k}{j}", u, v, int(rng.integers(3, 11))]
            for j, (u, v) in enumerate([(top, mid), (top, mid), (mid, "base"), (mid, "base"), (top, "base")])
        ]
        if k:
            runs.append([f"T{k}", f"top{k - 1}", mid, int(rng.integers(4, 8))])
    return {"name": f"synthetic-{zones}", "base": "base", "nodes": nodes, "lifts": lifts, "runs": runs}


def quantum_steps(T, n):
    n = max(n, 2)
    return np.sqrt(T) * n**1.5 * np.log2(n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--max-zones", type=int, default=5)
    ap.add_argument(
        "--overhead",
        type=float,
        default=1e4,
        help="assumed slowdown of one error-corrected quantum step vs one classical node visit",
    )
    a = ap.parse_args()

    print(f"budget {a.minutes:g} min, overhead {a.overhead:g}x\n")
    print(
        f"{'zones':>5} {'edges':>5} {'B&B tree T':>11} {'depth n':>7} {'Q steps':>10} {'B&B speedup':>11}"
        f" {'|F| routes':>11} {'Grover speedup':>14}"
    )
    m_s, logT = [], []
    for z in range(1, a.max_zones + 1):
        r = quasar.build(synthetic(z))
        _, T, n = quasar.search(r, "base", "base", a.minutes)
        F = len(quasar.search(r, "base", "base", a.minutes, prune=False)[0]) if z <= 3 else None
        q = quantum_steps(T, n)
        m_s.append(len(r["edges"]))
        logT.append(np.log10(T))
        grover = f"{np.sqrt(F):14.1f}" if F else f"{'(skipped)':>14}"
        print(f"{z:>5} {m_s[-1]:>5} {T:>11} {n:>7} {q:>10.0f} {T / q:>11.3f} {F or '':>11} {grover}")

    slope, icpt = np.polyfit(m_s, logT, 1)
    print(f"\nB&B tree grows ~10^{slope:.3f} per edge (fit over {len(m_s)} sizes).")
    # ponytail: depth n from the largest measured instance; it's capped by budget / shortest edge, so grows slowly
    T_star = (a.overhead * n**1.5 * np.log2(n)) ** 2
    m_star = (np.log10(T_star) - icpt) / slope
    print(f"With {a.overhead:g}x overhead and depth {n}, the quantum walk wins once T > {T_star:.1e} nodes,")
    print(f"i.e. a resort of ~{m_star:.0f} lifts+runs at this {a.minutes:g}-minute budget (extrapolated).")
