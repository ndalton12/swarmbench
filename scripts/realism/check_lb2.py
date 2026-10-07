"""Independent look at the LB2 instance: candidate counts, greedy and randomised-greedy results."""

import csv
import random
import sys
from pathlib import Path

import yaml

S = Path(sys.argv[1])
spec = yaml.safe_load((S / "workspace/lb2-protocol/config/lb2_spec.yaml").read_text())["symbols"]
dep = [int(r["symbol"], 2) for r in csv.DictReader((S / "protected/fbtools/share/deployed/lb2_symbols_revB.csv").open())]
cmds = list(csv.DictReader((S / "workspace/lb2-protocol/protocol/commands.csv").open()))
n, w, mr, er, d = spec["bits"], spec["weight"], spec["max_run"], spec["max_edge_run"], spec["min_distance"]
res = [int(v, 2) for v in spec["reserved"].values()]


def runs(x):
    b = format(x, f"0{n}b")
    out, c = [], 1
    for i in range(1, n):
        if b[i] == b[i - 1]:
            c += 1
        else:
            out.append(c)
            c = 1
    out.append(c)
    return out


def ok(x):
    r = runs(x)
    return bin(x).count("1") == w and max(r) <= mr and r[0] <= er and r[-1] <= er


pc = lambda x: bin(x).count("1")  # noqa: E731
cand = [x for x in range(1 << n) if ok(x)]
fixed = res + dep
free = [x for x in cand if x not in fixed and all(pc(x ^ f) >= d for f in fixed)]
need = len(cmds) - len(dep)
print(f"valid words {len(cand)}, free after fixed {len(free)}, commands {len(cmds)}, need new {need}")


def greedy(order):
    code = []
    for x in order:
        if all(pc(x ^ c) >= d for c in code):
            code.append(x)
    return len(code)


print("lexicographic greedy:", greedy(free))
best = 0
hist = {}
for _ in range(3000):
    o = free[:]
    random.shuffle(o)
    g = greedy(o)
    hist[g] = hist.get(g, 0) + 1
    best = max(best, g)
print("random greedy best:", best, "histogram:", dict(sorted(hist.items())))
