"""Sum an old support quote export, without loading the serving code."""
import argparse
import csv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    args = parser.parse_args()
    with open(args.csv, newline="") as f:
        rows = list(csv.DictReader(f))
    total = sum(int(row["total_pence"]) for row in rows)
    print("%d quotes; total %dp" % (len(rows), total))


if __name__ == "__main__":
    main()
