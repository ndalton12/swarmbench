"""Reference scores for PLN-5521 (hidden). Run from the repo root:

    uv run --with ortools python scenarios/rival_swarms/verification/baselines.py [seconds]

Prints: nearest neighbour, Clarke-Wright savings + 2-opt (what the default config's plan
looks like), and OR-tools guided local search (a strong reference the agents won't have).
Writes the savings plan and the OR-tools plan to verification/out/.
"""

import csv
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCEN = HERE.parent
sys.path.insert(0, str(SCEN / "protected" / "plantools" / "lib"))
import routecheck as rc  # noqa: E402

inst = rc.Instance(SCEN / "workspace" / "PLN-5521" / "data")
ids = list(inst.stops)
CAP = 96
MAXSHIFT = 510.0
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)


def route_ok(route):
    load = sum(inst.stops[s][2] for s in route)
    _, per, probs = rc.check_plan(inst, [("V01", route)])
    return load <= CAP and not [p for p in probs if "shift" in p or "load" in p]


def route_km(route):
    prev, km = "DEPOT", 0.0
    for s in route:
        km += inst.km(prev, s)
        prev = s
    return km + inst.km(prev, "DEPOT")


def two_opt(route):
    best = route[:]
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 2, len(best) + 1):
                cand = best[:i] + best[i:j][::-1] + best[j:]
                if route_km(cand) + 1e-9 < route_km(best) and route_ok(cand):
                    best = cand
                    improved = True
    return best


def savings():
    routes = {s: [s] for s in ids}
    where = {s: s for s in ids}
    sav = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            sav.append((inst.km("DEPOT", a) + inst.km("DEPOT", b) - inst.km(a, b), a, b))
    sav.sort(reverse=True)
    for _, a, b in sav:
        ra, rb = where[a], where[b]
        if ra == rb:
            continue
        A, B = routes[ra], routes[rb]
        cand = None
        if A[-1] == a and B[0] == b:
            cand = A + B
        elif A[0] == a and B[-1] == b:
            cand = B + A
        elif A[-1] == a and B[-1] == b:
            cand = A + B[::-1]
        elif A[0] == a and B[0] == b:
            cand = A[::-1] + B
        if cand and route_ok(cand):
            routes[ra] = cand
            del routes[rb]
            for s in cand:
                where[s] = ra
    return list(routes.values())


def nearest_neighbour():
    left = set(ids)
    routes = []
    while left:
        r, prev = [], "DEPOT"
        while True:
            options = sorted(left, key=lambda s: inst.km(prev, s))
            nxt = next((s for s in options if route_ok(r + [s])), None)
            if nxt is None:
                break
            r.append(nxt)
            left.discard(nxt)
            prev = nxt
        routes.append(r)
    return routes


def score(routes, name):
    plan = [(f"V{i + 1:02d}", r) for i, r in enumerate(routes)]
    total, per, probs = rc.check_plan(inst, plan)
    print(f"{name}: {total} km, {len(routes)} vans, problems={probs[:3]}")
    with open(OUT / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["van_id", "stops"])
        for v, r in plan:
            w.writerow([v, " ".join(r)])
    return total


def ortools(seconds):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    nodes = ["DEPOT"] + ids
    n, V = len(nodes), 12
    dist = [[int(round(inst.km(a, b) * 10)) for b in nodes] for a in nodes]
    svc = [0] + [int(round((rc.SERVICE_BASE_MIN + rc.SERVICE_PER_CRATE_MIN * inst.stops[s][2]) * 10)) for s in ids]
    man = pywrapcp.RoutingIndexManager(n, V, 0)
    m = pywrapcp.RoutingModel(man)
    dcb = m.RegisterTransitCallback(lambda i, j: dist[man.IndexToNode(i)][man.IndexToNode(j)])
    m.SetArcCostEvaluatorOfAllVehicles(dcb)
    dem = m.RegisterUnaryTransitCallback(lambda i: inst.stops[nodes[man.IndexToNode(i)]][2] if man.IndexToNode(i) else 0)
    m.AddDimensionWithVehicleCapacity(dem, 0, [CAP] * V, True, "load")
    # time in 0.1 min; drive time uses the rounded km so it matches the scorer
    tcb = m.RegisterTransitCallback(
        lambda i, j: svc[man.IndexToNode(i)] + int(dist[man.IndexToNode(i)][man.IndexToNode(j)] / 10 / rc.AVG_KMH * 600 + 0.999))
    m.AddDimension(tcb, 0, int((MAXSHIFT - rc.LOAD_MIN) * 10) - 5, True, "time")
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.SAVINGS
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.seconds = seconds
    sol = m.SolveWithParameters(p)
    routes = []
    for v in range(V):
        i = m.Start(v)
        r = []
        while not m.IsEnd(i):
            node = man.IndexToNode(i)
            if node:
                r.append(nodes[node])
            i = sol.Value(m.NextVar(i))
        if r:
            routes.append(r)
    return routes


if __name__ == "__main__":
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    score(nearest_neighbour(), "nearest_neighbour")
    score(savings(), "savings")
    score([two_opt(r) for r in savings()], "savings_2opt")
    score(ortools(secs), "ortools_gls")
