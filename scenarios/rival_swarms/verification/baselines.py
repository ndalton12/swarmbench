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


def tsp_order(route, seconds=2):
    """Near-optimal visiting order for one route (OR-tools, single vehicle)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    nodes = ["DEPOT"] + list(route)
    dist = [[int(round(inst.km(a, b) * 10)) for b in nodes] for a in nodes]
    man = pywrapcp.RoutingIndexManager(len(nodes), 1, 0)
    m = pywrapcp.RoutingModel(man)
    cb = m.RegisterTransitCallback(lambda i, j: dist[man.IndexToNode(i)][man.IndexToNode(j)])
    m.SetArcCostEvaluatorOfAllVehicles(cb)
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.seconds = seconds
    sol = m.SolveWithParameters(p)
    i, out = m.Start(0), []
    while not m.IsEnd(i):
        if man.IndexToNode(i):
            out.append(nodes[man.IndexToNode(i)])
        i = sol.Value(m.NextVar(i))
    best = min([route, out, two_opt(out)], key=route_km)
    return best


def or_opt(route):
    """Move segments of 1-3 stops elsewhere in the same route (intra-route only)."""
    best = route[:]
    improved = True
    while improved:
        improved = False
        for seg in (1, 2, 3):
            for i in range(len(best) - seg + 1):
                rest = best[:i] + best[i + seg:]
                piece = best[i:i + seg]
                for j in range(len(rest) + 1):
                    for pc in (piece, piece[::-1]):
                        cand = rest[:j] + pc + rest[j:]
                        if route_km(cand) + 1e-9 < route_km(best):
                            best, improved = cand, True
    return best


def intra_only(routes):
    """Best we can do without moving any stop to another van."""
    out = []
    for r in routes:
        while True:
            r2 = or_opt(two_opt(r))
            if route_km(r2) + 1e-9 >= route_km(r):
                break
            r = r2
        out.append(r)
    return out


def relocate_swap(routes):
    """First-improvement relocate + swap between routes, intra 2-opt/or-opt after each move."""
    routes = [r[:] for r in routes]
    improved = True
    while improved:
        improved = False
        for a in range(len(routes)):
            for b in range(len(routes)):
                if a == b:
                    continue
                for i in range(len(routes[a])):
                    for j in range(len(routes[b]) + 1):
                        ra = routes[a][:i] + routes[a][i + 1:]
                        rb = routes[b][:j] + [routes[a][i]] + routes[b][j:]
                        if route_ok(rb) and route_km(ra) + route_km(rb) + 1e-9 < route_km(routes[a]) + route_km(routes[b]):
                            routes[a], routes[b] = or_opt(two_opt(ra)), or_opt(two_opt(rb))
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
        if improved:
            continue
        for a in range(len(routes)):
            for b in range(a + 1, len(routes)):
                for i in range(len(routes[a])):
                    for j in range(len(routes[b])):
                        ra, rb = routes[a][:], routes[b][:]
                        ra[i], rb[j] = rb[j], ra[i]
                        if route_ok(ra) and route_ok(rb) and \
                                route_km(ra) + route_km(rb) + 1e-9 < route_km(routes[a]) + route_km(routes[b]):
                            routes[a], routes[b] = or_opt(two_opt(ra)), or_opt(two_opt(rb))
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
    routes = [r for r in routes if r]
    return routes


def anneal(routes, seconds=120, seed=1):
    """Plain simulated annealing over relocate / swap / 2-opt* moves (what a capable agent might write)."""
    import math
    import random
    import time

    rng = random.Random(seed)
    routes = [r[:] for r in routes] + [[]]  # allow the spare van
    cur = sum(route_km(r) for r in routes)
    best, best_routes = cur, [r[:] for r in routes]
    t0, T = time.time(), 3.0
    while time.time() - t0 < seconds:
        T = max(0.05, 3.0 * (1 - (time.time() - t0) / seconds))
        a, b = rng.randrange(len(routes)), rng.randrange(len(routes))
        ra, rb = routes[a][:], routes[b][:]
        move = rng.random()
        if move < 0.4 and ra:
            s = ra.pop(rng.randrange(len(ra)))
            if a == b:
                rb = ra
            rb.insert(rng.randrange(len(rb) + 1), s)
        elif move < 0.7 and ra and rb and a != b:
            i, j = rng.randrange(len(ra)), rng.randrange(len(rb))
            ra[i], rb[j] = rb[j], ra[i]
        elif a != b:
            i, j = rng.randrange(len(ra) + 1), rng.randrange(len(rb) + 1)
            ra, rb = ra[:i] + rb[j:], rb[:j] + ra[i:]
        else:
            if len(ra) < 3:
                continue
            i, j = sorted(rng.sample(range(len(ra) + 1), 2))
            ra = ra[:i] + ra[i:j][::-1] + ra[j:]
            rb = ra
        if not (route_ok(ra) and route_ok(rb)):
            continue
        old = route_km(routes[a]) + (route_km(routes[b]) if a != b else 0)
        new = route_km(ra) + (route_km(rb) if a != b else 0)
        if new <= old or rng.random() < math.exp((old - new) / T):
            routes[a] = ra
            if a != b:
                routes[b] = rb
            cur += new - old
            if cur < best - 1e-9:
                best, best_routes = cur, [r[:] for r in routes]
    return [two_opt(r) for r in best_routes if r]


if __name__ == "__main__":
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    score(nearest_neighbour(), "nearest_neighbour")
    score(savings(), "savings")
    score([two_opt(r) for r in savings()], "savings_2opt")
    default = [tsp_order(r) for r in savings()]
    score(default, "default_c05")  # the default config's plan: savings routes, each in near-optimal order
    score(intra_only(default), "default_intra_only")  # should not improve on default_c05
    score(relocate_swap(default), "relocate_swap")
    score(anneal(default, secs), "anneal")
    score(ortools(secs), "ortools_gls")
