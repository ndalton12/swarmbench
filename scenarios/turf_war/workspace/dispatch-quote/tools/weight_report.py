"""Draft purchasing report. TODO: group by packaging family."""
import json
from pathlib import Path

rows = json.loads((Path(__file__).resolve().parents[1] / "data/catalogue.json").read_text())
for sku, row in sorted(rows.items(), key=lambda pair: pair[1]["grams"], reverse=True):
    print("%s: %dg" % (sku, row["grams"]))
