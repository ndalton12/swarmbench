import argparse
import json
import sys

from .writer import convert


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("convert")
    command.add_argument("--type", choices=["SHP", "MNF", "RTN", "CNS", "INV", "CLM"], required=True)
    command.add_argument("input")
    args = parser.parse_args()
    try:
        with open(args.input) as f:
            for line in f:
                print(convert(args.type, json.loads(line)))
    except (OSError, ValueError, KeyError) as exc:
        print(f"xconv: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
