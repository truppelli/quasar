"""QWOA as a Qiskit circuit on one lift pod: checked against quasar.qwoa, sampled, and sized for IonQ hardware.

python circuit.py resorts/crystal-mountain-washington.json --pod "Rainier Express"

Routes are indexed 0..M-1 in an n = ceil(log2 M) qubit register. Each layer is the phase separator, one diagonal
gate exp(-i gamma C), and the walk mixer exp(-i beta A) on the complete graph of routes, which equals
U (phase on |0...0>) U^dagger with U the uniform state prep over the M valid indices. Indices >= M never gain
amplitude. ponytail: DiagonalGate and StatePreparation are exact but O(2^n) gates; fine to ~10 qubits, an arithmetic
cost oracle is the upgrade path for bigger pods.
"""

import argparse
import math
import sys
import warnings

import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.circuit.library import DiagonalGate, StatePreparation
from qiskit.primitives import StatevectorSampler
from qiskit.quantum_info import Statevector
from qiskit_ionq import IonQProvider
from qiskit_ionq.exceptions import IonQTranspileLevelWarning

import quasar


def qwoa_circuit(scores, theta):
    """QWOA circuit (no measurement) whose first len(scores) basis states are the routes."""
    C = quasar.qwoa_cost(scores)
    M, p = len(C), len(theta) // 2
    n = max(1, math.ceil(math.log2(M)))
    pad = 2**n - M
    prep = StatePreparation(np.r_[np.full(M, M**-0.5), np.zeros(pad)])
    qc = QuantumCircuit(n)
    qc.append(prep, range(n))
    for g, b in zip(theta[:p], theta[p:]):
        qc.append(DiagonalGate(np.r_[np.exp(-1j * g * C), np.ones(pad)]), range(n))
        qc.append(prep.inverse(), range(n))
        qc.x(range(n))
        qc.mcp(-b * M, list(range(n - 1)), n - 1)  # exp(-i b M) on |0...0>, i.e. on the uniform route state
        qc.x(range(n))
        qc.append(prep, range(n))
    return qc


def native_counts(qc, backend):
    """Gate counts after compiling to an IonQ backend's native gates. Offline: no API key or job needed."""
    warnings.simplefilter("ignore", IonQTranspileLevelWarning)  # fires on backend creation; we pass level 1 below
    b = IonQProvider(token="offline").get_backend(backend, gateset="native")
    t = transpile(qc, backend=b, optimization_level=1)
    return dict(t.count_ops()), t.depth()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("resort", nargs="?", default="resorts/toy.json")
    ap.add_argument("--pod", metavar="LIFT", default="Lift A", help="lift pod to run (see quasar.py --pods)")
    ap.add_argument("--minutes", type=float, help="time budget (default: the pod's QWOA budget)")
    ap.add_argument("--max-routes", type=int, default=512, help="size the budget to at most this many routes")
    ap.add_argument("--p", type=int, default=3, help="QWOA layers")
    ap.add_argument("--shots", type=int, default=1000)
    a = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    pod = next((p for p in quasar.pods(quasar.load(a.resort)) if p["lift"] == a.pod), None)
    if pod is None:
        ap.error(f"no pod for lift {a.pod!r}; see quasar.py --pods")
    minutes = a.minutes or (quasar.pod_budget(pod, a.max_routes) or ap.error("pod too big for QWOA; pass --minutes"))[0]
    sols, _, _ = quasar.search(pod, pod["base"], pod["base"], minutes, prune=False)
    scores = np.array([s for s, _ in sols.values()])
    probs, theta = quasar.qwoa(scores, p=a.p)
    opt = np.isclose(scores, scores.max())

    qc = qwoa_circuit(scores, theta)
    circ = Statevector(qc).probabilities()
    gap = np.abs(circ[: len(scores)] - probs).max()
    assert gap < 1e-8 and circ[len(scores) :].sum() < 1e-8, f"circuit differs from quasar.qwoa by {gap:.2e}"
    print(f"{pod['name']}, {minutes:g} min: {len(scores)} routes on {qc.num_qubits} qubits, p={a.p}")
    print(
        f"  circuit matches quasar.qwoa (max probability gap {gap:.1e}); P(optimal) = {probs[opt].sum():.3f} vs {opt.mean():.3f} random"
    )

    qc.measure_all()
    counts = StatevectorSampler(seed=0).run([qc], shots=a.shots).result()[0].data.meas.get_int_counts()
    hits = sum(c for k, c in counts.items() if k < len(scores) and opt[k])
    best = max(scores[k] for k in counts if k < len(scores))
    print(f"  {a.shots} shots: optimum sampled {hits} times, best sampled score {best:.0f} of {scores.max():.0f}")

    for backend in ("qpu.aria-1", "qpu.forte-1"):
        ops, depth = native_counts(qc, backend)
        two_q = ops.get("ms", 0) + ops.get("zz", 0)
        print(f"  IonQ {backend}: {two_q} two-qubit gates, depth {depth} ({ops})")
