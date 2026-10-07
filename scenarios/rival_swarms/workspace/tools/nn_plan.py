#!/usr/bin/env python3
"""Nearest-neighbour starting plan.  usage: nn_plan.py PLN-xxxx out.csv

Quick and bad (usually 30-40 % worse than the default plan), only meant as a
starting point for local search. Ignores the spare-van note (see known issues).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_utils as pu  # noqa: E402


def main():
    ticket, out = sys.argv[1], sys.argv[2]
    stops, vans = pu.load(ticket)
    left = set(stops) - {"DEPOT"}
    plan = {}
    for van, (cap, max_shift) in sorted(vans.items()):
        route, prev = [], "DEPOT"
        while left:
            for s in sorted(left, key=lambda s: pu.km(stops, prev, s)):
                cand = route + [s]
                if pu.route_load(stops, cand) <= cap and pu.route_shift(stops, cand) <= max_shift:
                    route.append(s)
                    left.discard(s)
                    prev = s
                    break
            else:
                break
        plan[van] = route
    if left:
        print(f"{len(left)} drops left over", file=sys.stderr)
    pu.write_plan(out, plan)
    print(f"wrote {out}: {sum(pu.route_km(stops, r) for r in plan.values() if r):.1f} km")


if __name__ == "__main__":
    main()
