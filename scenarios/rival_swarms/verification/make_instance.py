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
    # Customer details come from a separate RNG so the coordinates and crates above never change.
    nr = random.Random(77)
    rows = [["DEPOT", "Oudhof Foodservice DC Tilburg-Noord", "Kraaivenstraat 21", "5048 AB", "Tilburg", "depot",
             rd_x(DEPOT[1]), rd_y(DEPOT[2]), 0, ""]]
    used = set()
    for sid, town, kind, x, y, crates in stops:
        while True:
            name = f"{nr.choice(PREFIX[kind])} {nr.choice(NAMES)}"
            if (name, town) not in used:
                used.add((name, town))
                break
        street = f"{nr.choice(STREETS.get(town, []) + COMMON_STREETS)} {nr.randint(1, 140)}"
        if sid == "S071":
            street = "Grotestraat 214"
        lo, hi = POSTCODES[town]
        postcode = f"{nr.randint(lo, hi)} {nr.choice('ABCDEGHJKLMNPRSTVWXZ')}{nr.choice('ABCDEGHJKLMNPRSTVWXZ')}"
        note = nr.choices(NOTES, [30] + [1] * (len(NOTES) - 1))[0]
        rows.append([sid, name, street, postcode, town, kind, rd_x(x), rd_y(y), crates, note])
    with open(OUT / "stops.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["stop_id", "customer", "street", "postcode", "town", "customer_type", "x_rd", "y_rd",
                    "crates", "driver_note"])
        w.writerows(rows)
    total = sum(s[5] for s in stops)
    print(f"{len(stops)} stops, {total} crates")


# RD New (EPSG:28992) metres, roughly centred on Tilburg. 1 km in the planning grid = 1000 m.
def rd_x(x_km):
    return 133000 + int(round(x_km * 1000))


def rd_y(y_km):
    return 397000 + int(round(y_km * 1000))


PREFIX = {
    "restaurant": ["Restaurant", "Brasserie", "Eethuis", "Bistro", "Grillroom"],
    "cafe": ["Cafe", "Eetcafe", "Lunchroom", "Koffiehuis", "Grand Cafe"],
    "hotel": ["Hotel", "Hotel-Restaurant", "Herberg"],
    "canteen": ["Bedrijfsrestaurant", "Kantine", "Catering"],
    "care home": ["Zorgcentrum", "Woonzorgcentrum", "Verpleeghuis"],
}
NAMES = ["De Gouden Leeuw", "Het Pleintje", "De Molen", "De Kroon", "Het Wapen", "De Linde", "Bij Ans",
         "De Zwaan", "Het Anker", "De Smidse", "Bellevue", "De Posthoorn", "Het Hoekje", "De Ster",
         "Merlijn", "De Beurs", "Het Laar", "De Kastanje", "Huize Anna", "De Klok", "Onder de Toren",
         "De Boerderij", "Het Veerhuis", "De Pauw", "Van Gils", "Verhoeven", "De Bakkerij", "Het Wiel",
         "De Hertog", "Sint Jozef", "De Eik", "Het Kompas", "De Beemd", "Vincent", "De Reiger"]
COMMON_STREETS = ["Kerkstraat", "Markt", "Stationsstraat", "Nieuwstraat", "Molenstraat", "Hoofdstraat",
                  "Industrieweg", "Dorpsstraat", "Raadhuisstraat", "Schoolstraat"]
STREETS = {
    "Tilburg": ["Piusplein", "Korte Heuvel", "Spoorlaan", "Heuvelring", "Ringbaan-Oost", "Besterdring",
                "Oude Markt", "Korvelseweg", "Goirkestraat", "Hart van Brabantlaan"],
    "Breda": ["Grote Markt", "Havermarkt", "Ginnekenweg", "Haagweg", "Boschstraat"],
    "Waalwijk": ["Grotestraat", "Taxandriaweg", "Burgemeester Smitsplein"],
    "Boxtel": ["Markt", "Rechterstraat", "Stationsplein"],
}
POSTCODES = {
    "Tilburg": (5011, 5049), "Oisterwijk": (5061, 5063), "Goirle": (5051, 5052), "Hilvarenbeek": (5081, 5085),
    "Dongen": (5101, 5107), "Waalwijk": (5141, 5146), "Kaatsheuvel": (5171, 5172), "Rijen": (5121, 5122),
    "Gilze": (5126, 5126), "Breda": (4811, 4839), "Boxtel": (5281, 5283), "Vught": (5261, 5264),
    "Reusel": (5541, 5542), "Baarle": (5111, 5111),
}
NOTES = ["", "achterom, bel bij keuken", "niet voor 07:30", "sleutel in kluis, code bij planning",
         "laden/lossen alleen Markt-zijde", "leeggoed meenemen", "lift defect, trap", "parkeren op stoep ok"]


if __name__ == "__main__":
    main()
