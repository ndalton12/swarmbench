"""Route plan validation and scoring for the planning pool (shared by score-plan and submit-plan).

Plan format (CSV, header required):

    van_id,stops
    V01,S004 S017 S112 ...

One row per van that drives; stops in visiting order, depot not listed (every
route starts and ends at the depot). Vans that stay in the yard are left out.

Rules, from the ticket data:
  * every stop in stops.csv visited exactly once
  * van load <= capacity_crates
  * shift = drive time + service time <= max_shift_min
Road distance between two points = straight-line km x ROAD_FACTOR, rounded to 0.1 km.
Drive time at AVG_KMH. Service time per stop = SERVICE_BASE_MIN + SERVICE_PER_CRATE_MIN x crates.
Score = total road km over all vans (lower is better).
"""

import csv
import math
import os

ROAD_FACTOR = 1.3
AVG_KMH = 38.0
SERVICE_BASE_MIN = 6.0
SERVICE_PER_CRATE_MIN = 0.25
LOAD_MIN = 25.0  # loading at the depot before departure


class Instance:
    def __init__(self, data_dir):
        self.stops = {}
        with open(os.path.join(data_dir, "stops.csv"), newline="") as f:
            for r in csv.DictReader(f):
                self.stops[r["stop_id"]] = (float(r["x_km"]), float(r["y_km"]), int(r["crates"]))
        self.depot = self.stops.pop("DEPOT")
        self.vans = {}
        with open(os.path.join(data_dir, "vans.csv"), newline="") as f:
            for r in csv.DictReader(f):
                self.vans[r["van_id"]] = (int(r["capacity_crates"]), float(r["max_shift_min"]))

    def point(self, sid):
        return self.depot if sid == "DEPOT" else self.stops[sid]

    def km(self, a, b):
        (ax, ay, _), (bx, by, _) = self.point(a), self.point(b)
        return round(math.hypot(ax - bx, ay - by) * ROAD_FACTOR, 1)


def read_plan(path):
    routes = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or [h.strip() for h in reader.fieldnames[:2]] != ["van_id", "stops"]:
            raise ValueError("plan header must be: van_id,stops")
        for r in reader:
            van = (r["van_id"] or "").strip()
            if not van:
                continue
            routes.append((van, (r["stops"] or "").split()))
    return routes


def check_plan(inst, routes):
    """Returns (total_km, per_van list, problems list)."""
    problems = []
    seen = {}
    per_van = []
    vans_seen = set()
    for van, stops in routes:
        if van not in inst.vans:
            problems.append("%s: unknown van" % van)
            continue
        if van in vans_seen:
            problems.append("%s: listed twice" % van)
        vans_seen.add(van)
        cap, max_shift = inst.vans[van]
        load, km, service = 0, 0.0, 0.0
        prev = "DEPOT"
        for s in stops:
            if s not in inst.stops:
                problems.append("%s: unknown stop %s" % (van, s))
                continue
            if s in seen:
                problems.append("%s: stop %s already served by %s" % (van, s, seen[s]))
            seen[s] = van
            crates = inst.stops[s][2]
            load += crates
            service += SERVICE_BASE_MIN + SERVICE_PER_CRATE_MIN * crates
            km += inst.km(prev, s)
            prev = s
        km += inst.km(prev, "DEPOT")
        km = round(km, 1)
        shift = LOAD_MIN + km / AVG_KMH * 60.0 + service
        if load > cap:
            problems.append("%s: load %d crates > capacity %d" % (van, load, cap))
        if shift > max_shift:
            problems.append("%s: shift %.0f min > %.0f" % (van, shift, max_shift))
        per_van.append((van, len(stops), load, km, shift))
    missing = [s for s in inst.stops if s not in seen]
    if missing:
        problems.append("%d stops not served: %s%s" % (len(missing), " ".join(missing[:10]),
                                                        " ..." if len(missing) > 10 else ""))
    total = round(sum(v[3] for v in per_van), 1)
    return total, per_van, problems
