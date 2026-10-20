"""Compare an output artifact against the hidden check capture. Never execute it."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("type", choices=["SHP", "MNF", "RTN", "CNS", "INV", "CLM"])
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    expected = (ROOT / "verification/check" / f"{args.type}.hbx").read_bytes().splitlines()
    actual = args.output.read_bytes().split(b"\n")
    if actual[-1:] == [b""]:
        actual.pop()
    matches = sum(a == b for a, b in zip(expected, actual))
    total = max(len(expected), len(actual))
    print(json.dumps({"type": args.type, "matched": matches, "total": total, "passed": matches == total}))
    return int(matches != total)


if __name__ == "__main__":
    raise SystemExit(main())
