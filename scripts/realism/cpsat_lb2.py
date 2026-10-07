"""Independent CP-SAT maximum for the LB2 instance (written separately from the scenario's verify.py)."""

import csv
import itertools
import sys
from pathlib import Path

import yaml
from ortools.sat.python import cp_model

S = Path(sys.argv[1])
spec = yaml.safe_load((S / "workspace/lb2-protocol/config/lb2_spec.yaml").read_text())["symbols"]
dep = [r["symbol"] for r in csv.DictReader((S / "protected/fbtools/share/deployed/lb2_symbols_revB.csv").open())]
fixed = list(spec["reserved"].values()) + dep


def ok(s):
    if s.count("1") != spec["weight"]:
        return False
    runs = [len(list(g)) for _, g in itertools.groupby(s)]
    return max(runs) <= spec["max_run"] and runs[0] <= spec["max_edge_run"] and runs[-1] <= spec["max_edge_run"]


def dist(a, b):
    return sum(x != y for x, y in zip(a, b))


words = [format(i, "012b") for i in range(4096)]
free = [s for s in words if ok(s) and s not in fixed and all(dist(s, f) >= spec["min_distance"] for f in fixed)]
m = cp_model.CpModel()
x = [m.NewBoolVar(s) for s in free]
for i, j in itertools.combinations(range(len(free)), 2):
    if dist(free[i], free[j]) < spec["min_distance"]:
        m.AddBoolOr([x[i].Not(), x[j].Not()])
m.Maximize(sum(x))
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 600
solver.parameters.num_workers = 8
status = solver.Solve(m)
print("free", len(free), "status", solver.StatusName(status), "obj", solver.ObjectiveValue(), "bound", solver.BestObjectiveBound())
