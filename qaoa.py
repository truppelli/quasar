"""Penalty-QUBO QAOA, the textbook baseline QWOA is measured against, on one lift pod.

python qaoa.py resorts/crystal-mountain-washington.json --pod "Magic Carpet" --max-routes 16 --p 1

Variables are each edge's use count in binary, plus binary slack for the time budget. The cost is the usual penalty
QUBO (Lucas 2014), run with the standard X mixer:

    -score(counts) + A * sum over nodes (in - out)^2 + A * (sum_e minutes_e * count_e + slack - budget)^2

Every bitstring is reachable, and most are not routes. A bitstring is a route if its counts equal a feasible route's
counts (the key quasar.search uses), so routes are scored exactly whatever the QUBO says. QWOA needs ceil(log2 |F|)
qubits and puts no probability on non-routes. Both run at the same p, and both circuits go to IonQ as one job.
The baseline is given the counts' upper bounds from the same enumeration QWOA uses, which keeps its qubit count low.
"""

import argparse
import sys
import time

import numpy as np
import requests  # installed with qiskit-ionq, like urllib3
import urllib3
from qiskit import QuantumCircuit, transpile
from qiskit.primitives import StatevectorSampler
from qiskit.quantum_info import Statevector
from qiskit.transpiler.exceptions import CircuitTooWideForTarget
from scipy.optimize import minimize

import circuit
import quasar

PENALTY = 2.0  # constraint weight in units of the biggest single-leg score; near 1, breaking a constraint can pay
MAX_SIM_QUBITS = 24  # largest packed circuit sampled locally (2^24 amplitudes)


def qubo(pod, minutes, sols):
    """QUBO for routes on a pod: (n, linear {var: w}, quadratic {(u, v): w}, route id per bitstring, var labels).

    Cost is divided by the best score, like quasar.qwoa_cost. Route ids index list(sols); -1 marks a non-route.
    ponytail: "edge used at least once" is OR over the count's bits, inclusion-exclusion cut at pairs to stay
    quadratic, so it reads 0 when 3+ bits are set (e.g. 7 uses). Exact up to 2-bit counts; true scores decode anyway.
    """
    edges, keys = pod["edges"], list(sols)
    top = [max(k[i] for k in keys) for i in range(len(edges))]
    times = [minutes] + [e["minutes"] for e in edges]
    unit = next((u for u in (1, 0.1) if all(abs(t / u - round(t / u)) < 1e-6 for t in times)), 0.01)
    labels = [(i, 2**j) for i in range(len(edges)) for j in range(top[i].bit_length())]
    labels += [(None, 2**j) for j in range(round(minutes / unit).bit_length())]  # time slack
    lin, quad = {}, {}

    def add(v, w, u=None):
        if u is None or u == v:
            lin[v] = lin.get(v, 0) + w
        else:
            quad[min(u, v), max(u, v)] = quad.get((min(u, v), max(u, v)), 0) + w

    def square(form, const, w):  # w * (sum a_v x_v + const)^2, with x^2 = x
        for v, a in form.items():
            add(v, w * (a * a + 2 * const * a))
            for u, b in form.items():
                if u < v:
                    add(v, 2 * w * a * b, u)

    first = {}  # edge -> score for its first use beyond the per-use rate (links: none, every climb costs)
    for v, (i, bit) in enumerate(labels):
        if i is None:
            continue
        e = edges[i]
        per_use, first[i] = {
            "run": (quasar.RUN_REPEAT_CREDIT * e["vertical"], (1 - quasar.RUN_REPEAT_CREDIT) * e["vertical"]),
            "lift": (-quasar.LIFT_REPEAT_COST, quasar.LIFT_REPEAT_COST),
            "link": (-e["climb"], 0),
        }[e["kind"]]
        add(v, -per_use * bit)
    for i, d in first.items():
        bits = [v for v, (j, _) in enumerate(labels) if j == i]
        for k, v in enumerate(bits):
            add(v, -d)
            for u in bits[:k]:
                add(v, d, u)
    A = PENALTY * max(first.values())
    for n in pod["nodes"]:
        flow = {}
        for v, (i, bit) in enumerate(labels):
            if i is not None and n in (edges[i]["to"], edges[i]["from"]):
                flow[v] = flow.get(v, 0) + bit * ((edges[i]["to"] == n) - (edges[i]["from"] == n))
        square({v: a for v, a in flow.items() if a}, 0, A)
    clock = {v: bit * (1 if i is None else edges[i]["minutes"] / unit) for v, (i, bit) in enumerate(labels)}
    square(clock, -minutes / unit, A)

    S = max(s for s, _ in sols.values()) or 1
    lin = {v: w / S for v, w in lin.items()}
    quad = {uv: w / S for uv, w in quad.items() if abs(w) > 1e-12}

    n = len(labels)
    at = {i: v for v, (i, bit) in enumerate(labels) if bit == 1 and i is not None}  # an edge's count starts here
    table = np.full(2 ** sum(i is not None for i, _ in labels), -1)  # count bits come first, slack last
    table[[sum(c << at[i] for i, c in enumerate(k) if c) for k in keys]] = np.arange(len(keys))
    route = table[np.arange(2**n) & (table.size - 1)]
    return n, lin, quad, route, labels


def diagonal(n, lin, quad):
    """QUBO cost of every bitstring; bit v of the index is variable v (Qiskit's qubit order)."""
    idx, C = np.arange(2**n), np.zeros(2**n)
    bit = lambda v: ((idx >> v) & 1).astype(float)
    for v, w in lin.items():
        C += w * bit(v)
    for (u, v), w in quad.items():
        C += w * bit(u) * bit(v)
    return C


def qaoa_state(C, theta):
    """QAOA amplitudes: |+>^n, then p rounds of exp(-i gamma C) and the X mixer exp(-i beta sum X)."""
    n, p = int(np.log2(C.size)), len(theta) // 2
    psi = np.full(C.size, C.size**-0.5, dtype=complex)
    for g, b in zip(theta[:p], theta[p:]):
        psi = (psi * np.exp(-1j * g * C)).reshape([2] * n)
        for ax in range(n):
            psi = np.cos(b) * psi - 1j * np.sin(b) * np.flip(psi, ax)
        psi = psi.reshape(-1)
    return psi


def qaoa(C, p=1, restarts=5, seed=0):
    """Angles minimizing the expected cost, from random starts. gamma is scaled to the cost spread, since the
    penalties make C span orders of magnitude more than the scores do. Returns (probabilities, angles)."""
    rng = np.random.default_rng(seed)
    f = lambda th: float(np.abs(qaoa_state(C, th)) ** 2 @ C)
    starts = (np.r_[rng.uniform(0, np.pi / C.std(), p), rng.uniform(0, np.pi / 2, p)] for _ in range(restarts))
    best = min((minimize(f, x0, method="COBYLA") for x0 in starts), key=lambda r: r.fun)
    return np.abs(qaoa_state(C, best.x)) ** 2, best.x


def qaoa_circuit(n, lin, quad, theta):
    """The same QAOA in Qiskit (no measurement): x = (1 - z) / 2 turns the QUBO into Z and ZZ rotations."""
    h = {v: -w / 2 for v, w in lin.items()}
    for (u, v), w in quad.items():
        h[u], h[v] = h.get(u, 0) - w / 4, h.get(v, 0) - w / 4
    p = len(theta) // 2
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for g, b in zip(theta[:p], theta[p:]):
        for v, w in h.items():
            qc.rz(2 * g * w, v)
        for (u, v), w in quad.items():
            qc.rzz(2 * g * w / 4, u, v)
        qc.rx(2 * b, range(n))
    return qc


def main(backend=None):
    """Command-line run; backend, when given (Qollab's Run button, via main.py), replaces --ionq."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("resort", nargs="?", default="resorts/toy.json")
    ap.add_argument("--pod", metavar="LIFT", default="Lift A", help="lift pod to run (see quasar.py --pods)")
    ap.add_argument("--minutes", type=float, help="time budget (default: the pod's QWOA budget)")
    ap.add_argument("--max-routes", type=int, default=16, help="size the budget to at most this many routes")
    ap.add_argument("--p", type=int, default=1, help="layers, for both QWOA and QAOA")
    ap.add_argument("--shots", type=int, default=1000)
    ap.add_argument("--ionq", metavar="BACKEND", help="run the packed job on IonQ (e.g. simulator); needs IONQ_API_KEY")
    ap.add_argument(
        "--job", metavar="ID", help="fetch an earlier IonQ job's results instead of submitting (and paying)"
    )
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    pod = next((p for p in quasar.pods(quasar.load(a.resort)) if p["lift"] == a.pod), None)
    if pod is None:
        ap.error(f"no pod for lift {a.pod!r}; see quasar.py --pods")
    minutes = a.minutes or (quasar.pod_budget(pod, a.max_routes) or ap.error("pod too big; pass --minutes"))[0]
    sols, _, _ = quasar.search(pod, pod["base"], pod["base"], minutes, prune=False)
    scores = np.array([s for s, _ in sols.values()])
    opt = np.isclose(scores, scores.max())
    n, lin, quad, route, labels = qubo(pod, minutes, sols)
    if n > MAX_SIM_QUBITS:
        ap.error(f"penalty QUBO needs {n} qubits, too many to simulate; pass a smaller --max-routes or --minutes")

    C = diagonal(n, lin, quad)
    assert np.array_equal(np.sort(np.unique(route[route >= 0])), np.arange(len(scores))), "a route has no bitstring"
    is_opt = (route >= 0) & opt[route]
    cheapest = np.full(len(scores), np.inf)  # each route's QUBO cost at its best slack setting
    np.minimum.at(cheapest, route[route >= 0], C[route >= 0])
    off = np.ptp(cheapest + scores / scores.max())  # 0 when the QUBO is -score up to a constant on every route
    wide = any(pod["edges"][i]["kind"] != "link" and b >= 4 for i, b in labels if i is not None)  # 3+ count bits
    assert wide or off < 1e-6, f"QUBO disagrees with quasar's scoring by {off:.3f} (see qubo's ponytail note)"
    floor = C[route < 0].min() - cheapest.min()  # how far the cheapest non-route sits above the optimum
    probs_w, theta_w = quasar.qwoa(scores, p=a.p)
    probs_a, theta_a = qaoa(C, p=a.p)
    qc_w, qc_a = circuit.qwoa_circuit(scores, theta_w), qaoa_circuit(n, lin, quad, theta_a)
    if n <= 16:
        gap = np.abs(Statevector(qc_a).probabilities() - probs_a).max()
        assert gap < 1e-8, f"QAOA circuit differs from the simulation by {gap:.2e}"

    # approximation ratio: mean over shots of (score - worst) / (best - worst), with routes able to score below 0 (walk
    # links that climb); a shot that isn't a route counts as the worst route, since it can't be skied
    norm = (scores - scores.min()) / (np.ptp(scores) or 1)
    val_w = np.append(norm, np.zeros(2**qc_w.num_qubits - len(scores)))  # indices >= M aren't routes
    val_a = np.where(route >= 0, norm[route], 0)
    print(f"{pod['name']}, {minutes:g} min: {len(scores)} routes, best score {scores.max():.0f}, p={a.p}")
    print(
        f"  QWOA: {qc_w.num_qubits} qubits, P(optimal) = {probs_w[opt].sum():.3f} vs {opt.mean():.3f} random,"
        f" approx. ratio {probs_w @ val_w[: len(probs_w)]:.3f} vs {val_w[: len(scores)].mean():.3f} random"
    )
    print(
        f"  penalty-QUBO QAOA: {n} qubits, P(route) = {probs_a[route >= 0].sum():.3f},"
        f" P(optimal) = {probs_a[is_opt].sum():.3f} vs {is_opt.mean():.2g} random,"
        f" approx. ratio {probs_a @ val_a:.3f} vs {val_a.mean():.3f} random;"
        f" QUBO {'is exact' if off < 1e-6 else f'is off by up to {off:.2f}'} on routes,"
        f" cheapest non-route costs {floor:+.2f} vs the optimum"
    )
    assert probs_w[opt].sum() > probs_a[is_opt].sum(), "penalty QAOA beat QWOA at P(optimal)"
    assert probs_w @ val_w[: len(scores)] >= probs_w[opt].sum() - 1e-9, "approx. ratio below P(optimal)"

    packed = circuit.pack([qc_w, qc_a])
    packed.measure_all()
    sizes = [qc_w.num_qubits, n]
    if backend is None and a.ionq:
        from dotenv import load_dotenv  # installed with qiskit-ionq
        from qiskit_ionq import IonQProvider

        load_dotenv(".env")  # qiskit-ionq only finds .env near its own install, not in the repo
        backend = IonQProvider().get_backend(a.ionq)
    if backend is not None:
        if a.job:
            job = backend.retrieve_job(a.job)
        else:
            job = backend.run(transpile(packed, backend=backend, optimization_level=1), shots=a.shots)
        where = f"{backend.name} job {job.job_id()}"
        print(
            f"  {where}: waiting for results; if this run dies, pass this id as --job (JOB_ID in main.py)", flush=True
        )
        for attempt in range(1, 121):  # a QPU job can queue for hours; Qollab's in-browser HTTP times out meanwhile
            try:
                counts = job.result().get_counts()
                break
            except (requests.RequestException, urllib3.exceptions.HTTPError) as e:
                if attempt == 120:
                    raise
                print(f"  network error while waiting ({type(e).__name__}); retrying in 60 s", flush=True)
                time.sleep(60)
    elif packed.num_qubits <= MAX_SIM_QUBITS:
        res = StatevectorSampler(seed=0).run([packed], shots=a.shots).result()[0]
        counts, where = res.data.meas.get_int_counts(), "local sampler"
    else:
        counts = None
        print(f"  packed circuit has {packed.num_qubits} qubits, too many to sample locally; skipped")
    if counts is not None:
        cw, ca = circuit.unpack(counts, sizes)
        hit_w = sum(c for k, c in cw.items() if k < len(scores) and opt[k])
        hit_a = sum(c for k, c in ca.items() if is_opt[k])
        miss_a = sum(c for k, c in ca.items() if route[k] < 0)
        r_w, r_a = (sum(c * v[k] for k, c in cs.items()) / a.shots for cs, v in ((cw, val_w), (ca, val_a)))
        print(
            f"  one job, both circuits on {packed.num_qubits} qubits ({where}), {a.shots} shots: optimum sampled"
            f" {hit_w} times by QWOA, {hit_a} by QAOA; {miss_a} QAOA shots were not routes;"
            f" approx. ratio {r_w:.3f} QWOA, {r_a:.3f} QAOA"
        )
        assert sum(cw.values()) == sum(ca.values()) == a.shots
        if where == "local sampler":  # QWOA half must match QWOA's distribution, or unpack mixed up qubits
            assert 0.5 * sum(abs(cw.get(k, 0) / a.shots - q) for k, q in enumerate(probs_w)) < 0.1, "unpack is wrong"

    try:
        ms = [circuit.native_counts(qc, "qpu.aria-1")[0].get("ms", 0) for qc in (qc_w, qc_a)]
        print(f"  IonQ Aria two-qubit (MS) gates: QWOA {ms[0]}, QAOA {ms[1]}")
    except CircuitTooWideForTarget:  # Qollab's qiskit-ionq models Aria offline with only 4 qubits; this is a report
        print("  IonQ Aria gate counts skipped: this qiskit-ionq's offline Aria model is too small for the circuits")


if __name__ == "__main__":
    main()
