"""Load ticket data and compute route km/shift the same way score-plan does.

Same constants as plantools 2.1.
"""

import csv
import math
from pathlib import Path

ROAD_FACTOR = 1.3
AVG_KMH = 38.0
SERVICE_BASE_MIN = 6.0
SERVICE_PER_CRATE_MIN = 0.25



def load(ticket_dir):
    d = Path(ticket_dir) / "data"
    stops = {}
    with open(d / "stops.csv", newline="") as f:
        for r in csv.DictReader(f):
            stops[r["stop_id"]] = (int(r["x_rd"]) / 1000.0, int(r["y_rd"]) / 1000.0, int(r["crates"]))
    vans = {}
    with open(d / "vans.csv", newline="") as f:
        for r in csv.DictReader(f):
            vans[r["van_id"]] = (int(r["capacity_crates"]), float(r["max_shift_min"]))
    return stops, vans


def km(stops, a, b):
    (ax, ay, _), (bx, by, _) = stops[a], stops[b]
    return round(math.hypot(ax - bx, ay - by) * ROAD_FACTOR, 1)


def route_km(stops, route):
    path = ["DEPOT"] + list(route) + ["DEPOT"]
    return round(sum(km(stops, a, b) for a, b in zip(path, path[1:])), 1)


def route_shift(stops, route):
    service = sum(SERVICE_BASE_MIN + SERVICE_PER_CRATE_MIN * stops[s][2] for s in route)
    return route_km(stops, route) / AVG_KMH * 60.0 + service


def route_load(stops, route):
    return sum(stops[s][2] for s in route)


def read_plan(path):
    with open(path, newline="") as f:
        return {r["van_id"]: r["stops"].split() for r in csv.DictReader(f) if r["van_id"]}


def write_plan(path, plan):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["van_id", "stops"])
        for van in sorted(plan):
            if plan[van]:
                w.writerow([van, " ".join(plan[van])])
