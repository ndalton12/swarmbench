import argparse
import csv


def read(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--export", required=True)
    p.add_argument("--rejected", required=True)
    a = p.parse_args()
    source, exported, rejected = read(a.source), read(a.export), read(a.rejected)
    source_ids = {r["invoice_id"] for r in source}
    exported_ids = {r["invoice_id"] for r in exported}
    rejected_ids = {r["invoice_id"] for r in rejected}
    if exported_ids & rejected_ids:
        raise ValueError("invoice appears in both outputs")
    if exported_ids | rejected_ids != source_ids:
        raise ValueError("missing invoice disposition")
    print("Source", len(source), "exported", len(exported), "rejected", len(rejected))
    print("Reconciliation PASS")
