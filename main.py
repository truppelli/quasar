"""Qollab entry point: the hackathon demo, QWOA vs penalty-QUBO QAOA on one lift pod, packed into one IonQ job.

With no arguments (Qollab's Run button) it runs Crystal Mountain's Quicksilver pod, 17 qubits, on the backend picked
in Qollab's Select QPU dialog. python main.py [qaoa.py options] runs anything else, e.g. python main.py --minutes 30
"""

import runpy
import sys

sys.path.insert(0, ".")  # Qollab may run this without __file__; run it from the repo root
if len(sys.argv) <= 1:
    sys.argv = ["main.py", "resorts/crystal-mountain-washington.json", "--pod", "Quicksilver", "--max-routes", "4"]
runpy.run_path("qaoa.py", init_globals={"backend": globals().get("backend")}, run_name="__main__")
