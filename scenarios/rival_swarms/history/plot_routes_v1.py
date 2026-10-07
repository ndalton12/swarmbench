#!/usr/bin/env python3
"""ASCII map of a plan (no matplotlib on the workers).  usage: plot_routes.py PLN-xxxx plan.csv

Each van gets a letter, D is the depot.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_utils as pu  # noqa: E402


def main():
    ticket, plan_path = sys.argv[1], sys.argv[2]
    width = 100
    stops, _ = pu.load(ticket)
    plan = pu.read_plan(plan_path)
    xs = [p[0] for p in stops.values()]
    ys = [p[1] for p in stops.values()]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    height = int(width * (y1 - y0) / (x1 - x0) / 2) + 1
    grid = [[" "] * (width + 1) for _ in range(height + 1)]

    def put(sid, ch):
        x, y, _ = stops[sid]
        cx = int((x - x0) / (x1 - x0) * width)
        cy = height - int((y - y0) / (y1 - y0) * height)
        grid[cy][cx] = ch

    for i, van in enumerate(sorted(plan)):
        for s in plan[van]:
            put(s, chr(ord("A") + i))
    put("DEPOT", "D")
    print("\n".join("".join(r).rstrip() for r in grid))
    for i, van in enumerate(sorted(plan)):
        r = plan[van]
        print(f"{chr(ord('A') + i)} {van}: {len(r):3d} drops {pu.route_load(stops, r):3d} crates "
              f"{pu.route_km(stops, r):6.1f} km")


if __name__ == "__main__":
    main()
