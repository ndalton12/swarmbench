"""Compare two local HBX files without using a testgrid allocation."""
import argparse
from itertools import zip_longest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected")
    parser.add_argument("actual")
    args = parser.parse_args()
    expected = Path(args.expected).read_text().splitlines()
    actual = Path(args.actual).read_text().splitlines()
    matched = 0
    for n, (want, got) in enumerate(zip_longest(expected, actual), 1):
        if want == got:
            matched += 1
        elif n <= 40:
            print(f"line {n}: expected {want!r}\n         actual   {got!r}")
    print(f"{matched}/{max(len(expected), len(actual))} records match")
    return int(expected != actual)


if __name__ == "__main__":
    raise SystemExit(main())
