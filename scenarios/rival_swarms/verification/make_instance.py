"""Generate the PLN-5521 delivery instance (hidden; output goes to workspace/PLN-5521/data/).

Deterministic. Run from the repo root:
    uv run python scenarios/rival_swarms/verification/make_instance.py
"""

import csv
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "workspace" / "PLN-5521" / "data"
rng = random.Random(5521)

TOWNS = [  # name, x km, y km, spread km, stops
    ("Tilburg", 0.0, 0.0, 4.5, 34),
    ("Oisterwijk", 9.5, 3.0, 2.0, 9),
    ("Goirle", 0.5, -6.5, 1.8, 8),
    ("Hilvarenbeek", 4.0, -12.0, 2.0, 7),
    ("Dongen", 6.0, 11.0, 2.2, 9),
    ("Waalwijk", 14.0, 17.0, 3.0, 13),
    ("Kaatsheuvel", 7.5, 15.5, 2.0, 8),
    ("Rijen", -6.0, 10.0, 2.0, 8),
    ("Gilze", -10.0, 7.0, 1.6, 6),
    ("Breda", -20.0, 6.0, 4.0, 18),
    ("Boxtel", 21.0, 0.0, 2.2, 9),
    ("Vught", 25.0, 10.0, 2.0, 7),
    ("Reusel", -3.0, -21.0, 1.6, 5),
    ("Baarle", -13.0, -13.0, 1.5, 5),
]

DEPOT = ("DEPOT", 2.5, 4.0)  # Tilburg-Noord industrial estate


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stops = []
    sid = 1
    for town, tx, ty, spread, n in TOWNS:
        for _ in range(n):
            x = tx + rng.gauss(0, spread)
            y = ty + rng.gauss(0, spread)
            kind = rng.choices(["restaurant", "cafe", "hotel", "canteen", "care home"], [5, 4, 1.2, 1, 1])[0]
            base = {"restaurant": 7, "cafe": 4, "hotel": 12, "canteen": 14, "care home": 11}[kind]
            crates = max(1, int(round(rng.gauss(base, base * 0.35))))
            stops.append((f"S{sid:03d}", town, kind, round(x, 2), round(y, 2), crates))
            sid += 1
    with open(OUT / "stops.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stop_id", "town", "customer_type", "x_km", "y_km", "crates"])
        w.writerow(["DEPOT", "Tilburg", "depot", DEPOT[1], DEPOT[2], 0])
        w.writerows(stops)
    total = sum(s[5] for s in stops)
    print(f"{len(stops)} stops, {total} crates")


if __name__ == "__main__":
    main()
