#!/usr/bin/env python3
"""Fill unassigned opcodes in commands.csv with LB2 symbols.

Symbols that are already in the table (deployed ones and anything assigned
earlier) are kept as they are; only blank rows get filled.

random restarts: shuffle all valid words, greedy-add anything at distance >= 4
from what we have (table + reserved first), keep the best run.

    python3 tools/symsearch.py --restarts 200000 --seed 1 --write

TODO: smarter search (swap moves?), this tops out at 61
"""

import argparse
import csv
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import symlib  # noqa: E402

CSV = ROOT / "protocol" / "commands.csv"


def load():
    with open(CSV, newline="") as f:
        return list(csv.DictReader(f))


def search(fixed, restarts, seed):
    rng = random.Random(seed)
    cands = [w for w in symlib.all_symbols()
             if w not in fixed and all(symlib.distance(w, f) >= symlib.MIN_DISTANCE for f in fixed)]
    best = []
    t0 = time.time()
    for i in range(restarts):
        rng.shuffle(cands)
        chosen = []
        for w in cands:
            if all(symlib.distance(w, c) >= symlib.MIN_DISTANCE for c in chosen):
                chosen.append(w)
        if len(chosen) > len(best):
            best = chosen
            print(f"[{i}] {len(best)} new symbols ({time.time() - t0:.0f}s)", flush=True)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restarts", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    rows = load()
    assigned = [symlib.from_str(r["symbol"]) for r in rows if r["symbol"]]
    fixed = assigned + list(symlib.RESERVED.values())
    todo = [r for r in rows if not r["symbol"]]
    best = search(fixed, args.restarts, args.seed)
    print(f"best: {len(assigned) + len(best)}/{len(rows)}")
    if args.write:
        for r, w in zip(todo, best):
            r["symbol"] = symlib.to_str(w)
        with open(CSV, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)
        print(f"wrote {min(len(todo), len(best))} symbols to {CSV}")


if __name__ == "__main__":
    main()
