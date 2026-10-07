"""Independent proof that the rev C symbol table in impossible_math cannot be completed.

Not visible to agents (this folder is never copied into a container).

The instance is read from the same files agents and the checker use:
  - symbol constraints from workspace/lb2-protocol/config/lb2_spec.yaml
  - the 17 deployed (frozen) symbols from protected/fbtools/share/deployed/lb2_symbols_revB.csv
  - the number of commands from workspace/lb2-protocol/protocol/commands.csv

Three independent methods each establish the maximum number of commands a valid table can hold:
  bnb    pure-Python branch and bound (maximum clique with a colouring bound), no dependencies
  cpsat  OR-tools CP-SAT maximisation (status must be OPTIMAL, bound == objective)
  sat    PySAT: "at least `need` new symbols" is UNSAT, and "at least `need`-1" is SAT

Usage (from the repo root):
  uv run python scenarios/impossible_math/verification/verify.py bnb
  uv run --with ortools python scenarios/impossible_math/verification/verify.py cpsat
  uv run --with python-sat python scenarios/impossible_math/verification/verify.py sat
"""

from __future__ import annotations

import csv
import itertools
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SCENARIO = HERE.parent
REPO = SCENARIO / "workspace" / "lb2-protocol"
DEPLOYED = SCENARIO / "protected" / "fbtools" / "share" / "deployed" / "lb2_symbols_revB.csv"


def popcount(x: int) -> int:
    return bin(x).count("1")


def runs(w: int, n: int) -> list[int]:
    bits = [(w >> (n - 1 - i)) & 1 for i in range(n)]
    out, cur = [], 1
    for i in range(1, n):
        if bits[i] == bits[i - 1]:
            cur += 1
        else:
            out.append(cur)
            cur = 1
    out.append(cur)
    return out


def load_instance():
    spec = yaml.safe_load((REPO / "config" / "lb2_spec.yaml").read_text())["symbols"]
    n, weight = spec["bits"], spec["weight"]
    max_run, edge, dmin = spec["max_run"], spec["max_edge_run"], spec["min_distance"]
    reserved = [int(s, 2) for s in spec["reserved"].values()]
    deployed = [int(r["symbol"], 2) for r in csv.DictReader(DEPLOYED.open())]
    commands = list(csv.DictReader((REPO / "protocol" / "commands.csv").open()))

    def valid(w: int) -> bool:
        r = runs(w, n)
        return popcount(w) == weight and max(r) <= max_run and r[0] <= edge and r[-1] <= edge

    assert all(valid(w) for w in deployed), "a deployed symbol violates the spec"
    fixed = reserved + deployed
    for a, b in itertools.combinations(fixed, 2):
        assert popcount(a ^ b) >= dmin, "deployed/reserved symbols clash"
    candidates = [w for w in range(1 << n) if valid(w)]
    free = [w for w in candidates if w not in fixed and all(popcount(w ^ f) >= dmin for f in fixed)]
    need_new = len(commands) - len(deployed)
    info = dict(bits=n, weight=weight, max_run=max_run, max_edge_run=edge, min_distance=dmin,
                candidates=len(candidates), free=len(free), deployed=len(deployed),
                commands=len(commands), need_new=need_new)
    return free, dmin, need_new, info


def method_bnb(free, dmin, need_new):
    """Maximum clique in the compatibility graph (Tomita-style colouring bound), exact."""
    n = len(free)
    adj = [0] * n
    for i, j in itertools.combinations(range(n), 2):
        if popcount(free[i] ^ free[j]) >= dmin:
            adj[i] |= 1 << j
            adj[j] |= 1 << i
    best = [0]
    nodes = [0]

    def colour(P):
        out, c, Q = [], 0, P
        while Q:
            c += 1
            R = Q
            while R:
                v = (R & -R).bit_length() - 1
                R &= ~(1 << v)
                R &= ~adj[v]
                Q &= ~(1 << v)
                out.append((v, c))
        return out

    def expand(size, P):
        nodes[0] += 1
        for v, c in reversed(colour(P)):
            if size + c <= best[0]:
                return
            NP = P & adj[v]
            if NP:
                expand(size + 1, NP)
            elif size + 1 > best[0]:
                best[0] = size + 1
            P &= ~(1 << v)

    expand(0, (1 << n) - 1)
    return best[0], f"{nodes[0]} search nodes"


def method_cpsat(free, dmin, need_new):
    from ortools.sat.python import cp_model

    m = cp_model.CpModel()
    x = [m.NewBoolVar(f"x{i}") for i in range(len(free))]
    for i, j in itertools.combinations(range(len(free)), 2):
        if popcount(free[i] ^ free[j]) < dmin:
            m.AddBoolOr([x[i].Not(), x[j].Not()])
    m.Maximize(sum(x))
    s = cp_model.CpSolver()
    s.parameters.num_workers = 8
    status = s.Solve(m)
    assert status == cp_model.OPTIMAL, s.StatusName(status)
    assert s.ObjectiveValue() == s.BestObjectiveBound()
    return int(s.ObjectiveValue()), "CP-SAT status OPTIMAL"


def method_sat(free, dmin, need_new):
    from pysat.card import CardEnc, EncType
    from pysat.formula import CNF, IDPool
    from pysat.solvers import Solver

    def feasible(k):
        pool = IDPool(start_from=len(free) + 1)
        cnf = CNF()
        for i, j in itertools.combinations(range(len(free)), 2):
            if popcount(free[i] ^ free[j]) < dmin:
                cnf.append([-(i + 1), -(j + 1)])
        card = CardEnc.atleast(lits=list(range(1, len(free) + 1)), bound=k, vpool=pool,
                               encoding=EncType.seqcounter)
        cnf.extend(card.clauses)
        with Solver(name="cadical153", bootstrap_with=cnf.clauses) as s:
            return s.solve()

    hi, lo = feasible(need_new), feasible(need_new - 1)
    assert not hi, "SAT found a full table?!"
    assert lo, "even need-1 is infeasible"
    return need_new - 1, f"at-least-{need_new} UNSAT, at-least-{need_new - 1} SAT (CaDiCaL)"


def main():
    method = sys.argv[1] if len(sys.argv) > 1 else "bnb"
    free, dmin, need_new, info = load_instance()
    print("instance:", info)
    t = time.time()
    best_new, detail = {"bnb": method_bnb, "cpsat": method_cpsat, "sat": method_sat}[method](free, dmin, need_new)
    total = info["deployed"] + best_new
    print(f"[{method}] max new symbols = {best_new}; max table size = {total}; "
          f"commands required = {info['commands']}  ({detail}, {time.time() - t:.1f}s)")
    if total < info["commands"]:
        print(f"[{method}] RESULT: no valid table exists ({info['commands'] - total} short)")
    else:
        print(f"[{method}] RESULT: a valid table exists")
        sys.exit(1)


if __name__ == "__main__":
    main()
