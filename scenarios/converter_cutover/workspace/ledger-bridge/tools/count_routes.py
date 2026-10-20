"""Count stops in a depot route export."""
import csv
import sys
from collections import Counter

counts = Counter()
with open(sys.argv[1], newline="") as f:
    for row in csv.DictReader(f):
        counts[row["depot"]] += int(row["stops"])
for depot, count in sorted(counts.items()):
    print(f"{depot}: {count}")
