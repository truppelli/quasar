"""README charts: QWOA vs the penalty-QUBO QAOA baseline vs a random route, from noise-free simulation at p=1.

python charts.py   # needs matplotlib (pip install matplotlib); it isn't in requirements.txt, which Qollab installs

Writes docs/img/<chart>-light.png and -dark.png. The numbers are recomputed with the same functions qaoa.py uses
(exact probabilities, no sampling), so they match the README's baseline table.
"""

import matplotlib
import matplotlib.ticker
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import circuit
import qaoa
import quasar

CRYSTAL = "resorts/crystal-mountain-washington.json"
PODS = [  # (resort file, lift, minutes, label): the README baseline table's pods
    ("resorts/toy.json", "Lift A", 65, "Toy Lift A\n65 min"),
    (CRYSTAL, "Quicksilver", 17, "Quicksilver\n17 min"),
    (CRYSTAL, "Gold Hills", 11, "Gold Hills\n11 min"),
    (CRYSTAL, "Discovery", 13, "Discovery\n13 min"),
    (CRYSTAL, "Green Valley", 14, "Green Valley\n14 min"),
    (CRYSTAL, "Gold Hills", 13, "Gold Hills\n13 min"),
]
# Recorded IonQ jobs on Crystal Quicksilver (README "On IonQ's cloud simulators"): best route sampled, of 1,000 shots
IONQ = [
    ("Local sampler\n(noise-free)", 487, 3),
    ("IonQ cloud simulator\n(noise-free)", 500, 12),
    ("IonQ Forte Enterprise 1\nnoise model", 485, 5),
]
THEMES = {  # dataviz reference palette: categorical slots 1-3 (validated all-pairs) and chart chrome
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "grid": "#e1e0d9",
        "base": "#c3c2b7",
        "series": ("#2a78d6", "#eb6834", "#1baf7a"),
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#f0efec",
        "ink2": "#c3c2b7",
        "grid": "#2c2c2a",
        "base": "#383835",
        "series": ("#3987e5", "#d95926", "#199e70"),
    },
}
NAMES = ("QWOA", "Penalty-QUBO QAOA", "Random route")


def metrics(path, lift, minutes):
    """QWOA and QAOA at p=1 on one pod, exactly as qaoa.py computes them."""
    pod = next(p for p in quasar.pods(quasar.load(path)) if p["lift"] == lift)
    sols, _, _ = quasar.search(pod, pod["base"], pod["base"], minutes, prune=False)
    scores = np.array([s for s, _ in sols.values()])
    opt = np.isclose(scores, scores.max())
    n, lin, quad, route, _ = qaoa.qubo(pod, minutes, sols)
    probs_w, theta_w = quasar.qwoa(scores, p=1)
    probs_a, theta_a = qaoa.qaoa(qaoa.diagonal(n, lin, quad), p=1)
    norm = (scores - scores.min()) / (np.ptp(scores) or 1)  # approximation ratio per route; non-routes score 0
    is_route = route >= 0
    ms = [
        circuit.native_counts(qc, "qpu.aria-1")[0].get("ms", 0)
        for qc in (circuit.qwoa_circuit(scores, theta_w), qaoa.qaoa_circuit(n, lin, quad, theta_a))
    ]
    return {
        "p_opt": (probs_w[opt].sum(), probs_a[is_route & opt[route]].sum(), opt.mean()),
        "ratio": (probs_w @ norm, probs_a @ np.where(is_route, norm[route], 0), norm.mean()),
        "p_route": (probs_w.sum(), probs_a[is_route].sum()),
        "qubits": (circuit.qwoa_circuit(scores, theta_w).num_qubits, n),
        "gates": tuple(ms),
    }


def style(ax, t, title, ymax=None):
    ax.set_facecolor(t["surface"])
    ax.set_title(title, loc="left", fontsize=11, color=t["ink"], pad=8)
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["base"])
    ax.tick_params(colors=t["ink2"], length=0, labelsize=9)
    if ymax is not None:
        ax.set_ylim(0, ymax)


def bars(ax, t, labels, groups, label_series=(), fmt="{:.3f}"):
    """Grouped bars, one color per algorithm, a 2px surface gap between neighbours; values only on label_series."""
    k = len(groups[0])
    w = 0.8 / k
    x = np.arange(len(labels))
    for s in range(k):
        vals = [g[s] for g in groups]
        b = ax.bar(x + (s - (k - 1) / 2) * w, vals, w, color=t["series"][s], edgecolor=t["surface"], linewidth=2)
        if s in label_series:
            ax.bar_label(b, [fmt.format(v) for v in vals], padding=2, fontsize=8, color=t["ink2"])
    ax.set_xticks(x, labels)


def save(fig, name, mode, t):
    fig.patch.set_facecolor(t["surface"])
    fig.savefig(f"docs/img/{name}-{mode}.png", dpi=160, facecolor=t["surface"], bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    data = [metrics(*pod[:3]) for pod in PODS]
    labels = [pod[3] for pod in PODS]
    for d, pod in zip(data, PODS):  # same numbers as the README baseline table
        print(pod[3].replace("\n", " "), {k: tuple(round(float(v), 3) for v in vals) for k, vals in d.items()})
    # the ideal QWOA circuit never leaves the route register; QAOA rarely lands on one
    assert all(abs(d["p_route"][0] - 1) < 1e-9 and d["p_route"][1] < 0.1 for d in data)

    plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
    for mode, t in THEMES.items():
        fig, axes = plt.subplots(3, 1, figsize=(10, 10.5), sharex=True)
        style(axes[0], t, "Chance of sampling the best route", 1.12)
        bars(axes[0], t, labels, [d["p_opt"] for d in data], label_series=(1,))
        style(axes[1], t, "Approximation ratio (1 = the best route every shot)", 1.12)
        bars(axes[1], t, labels, [d["ratio"] for d in data], label_series=(1,))
        style(axes[2], t, "Share of the state on valid routes (the rest can't be skied)", 1.12)
        bars(axes[2], t, labels, [d["p_route"] for d in data], label_series=(1,), fmt="{:.1%}")
        fig.legend(
            [plt.Rectangle((0, 0), 1, 1, color=c) for c in t["series"]],
            NAMES,
            loc="upper left",
            ncol=3,
            frameon=False,
            bbox_to_anchor=(0.01, 1.0),
            labelcolor=t["ink"],
            fontsize=10,
        )
        fig.suptitle(
            "QWOA vs penalty-QUBO QAOA on six lift pods (noise-free simulation, p = 1)",
            x=0.01,
            y=1.04,
            ha="left",
            fontsize=13,
            color=t["ink"],
        )
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        save(fig, "qwoa-vs-baselines", mode, t)

        fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
        style(axes[0], t, "Qubits")
        axes[0].yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))  # qubits come whole
        bars(axes[0], t, labels, [d["qubits"] for d in data], label_series=(0, 1), fmt="{:.0f}")
        style(axes[1], t, "Two-qubit (MS) gates on IonQ Aria")
        bars(axes[1], t, labels, [d["gates"] for d in data], label_series=(0, 1), fmt="{:.0f}")
        for ax in axes:
            ax.tick_params(axis="x", labelsize=7)
        fig.legend(
            [plt.Rectangle((0, 0), 1, 1, color=c) for c in t["series"][:2]],
            NAMES[:2],
            loc="upper left",
            ncol=2,
            frameon=False,
            bbox_to_anchor=(0.01, 1.0),
            labelcolor=t["ink"],
            fontsize=10,
        )
        fig.suptitle(
            "What each algorithm costs on the same pod", x=0.01, y=1.07, ha="left", fontsize=13, color=t["ink"]
        )
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save(fig, "qwoa-resources", mode, t)

        fig, ax = plt.subplots(figsize=(10, 4.2))
        style(ax, t, "Best route sampled, of 1,000 shots (Crystal Quicksilver, one packed job each)", 600)
        bars(ax, t, [r[0] for r in IONQ], [r[1:] for r in IONQ], label_series=(0, 1), fmt="{:.0f}")
        fig.legend(
            [plt.Rectangle((0, 0), 1, 1, color=c) for c in t["series"][:2]],
            NAMES[:2],
            loc="upper left",
            ncol=2,
            frameon=False,
            bbox_to_anchor=(0.01, 1.0),
            labelcolor=t["ink"],
            fontsize=10,
        )
        fig.suptitle(
            "Same result on IonQ's simulators, with and without noise",
            x=0.01,
            y=1.07,
            ha="left",
            fontsize=13,
            color=t["ink"],
        )
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        save(fig, "qwoa-ionq", mode, t)
    print("wrote docs/img/{qwoa-vs-baselines,qwoa-resources,qwoa-ionq}-{light,dark}.png")
