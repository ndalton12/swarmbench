"""Cormac's scratch version. Not wired into Makefile."""
import csv
import sys

with open(sys.argv[1], newline="") as handle:
    rows = list(csv.DictReader(handle))

# TODO: needs rejected amounts from the source file, not just this output.
print("export net", sum(int(r["net_pence"]) for r in rows))
print("tax", sum(int(r["tax_pence"]) for r in rows))
