"""Qollab entry point: the hackathon demo, QWOA vs penalty-QUBO QAOA on one lift pod, packed into one IonQ job.

python main.py [qaoa.py options], e.g. python main.py resorts/crystal-mountain-washington.json --pod "Gold Hills"
"""

import runpy
import sys

sys.path.insert(0, ".")  # Qollab may run this without __file__; run it from the repo root
sys.argv = sys.argv or ["main.py"]
runpy.run_path("qaoa.py", run_name="__main__")
