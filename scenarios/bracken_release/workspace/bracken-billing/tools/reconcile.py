import argparse
import csv


def read(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def reconcile(source, exported, rejected):
    src = {r["invoice_id"]: r for r in source}
    if len(src) != len(source):
        raise ValueError("duplicate source identifiers")
    exp = {r["invoice_id"]: r for r in exported}
    rej = {r["invoice_id"]: r for r in rejected}
    if len(exp) != len(exported) or len(rej) != len(rejected):
        raise ValueError("duplicate output identifiers")
    if set(exp) & set(rej):
        raise ValueError("invoice appears in both outputs")
    if set(exp) | set(rej) != set(src):
        raise ValueError("source/output identifiers do not reconcile")
    for ident, row in exp.items():
        if row["merchant_id"] != src[ident]["merchant_id"]:
            raise ValueError(f"merchant changed for {ident}")
        if int(row["net_pence"]) != int(src[ident]["net_pence"]):
            raise ValueError(f"net changed for {ident}")
    for ident, row in rej.items():
        if row["merchant_id"] != src[ident]["merchant_id"]:
            raise ValueError(f"rejected merchant changed for {ident}")
    source_net = sum(int(r["net_pence"]) for r in source)
    exported_net = sum(int(r["net_pence"]) for r in exported)
    rejected_net = sum(int(src[i]["net_pence"]) for i in rej)
    print(f"Source rows: {len(source)}; net pence: {source_net}")
    print(f"Exported rows: {len(exported)}; net pence: {exported_net}")
    print(f"Rejected rows: {len(rejected)}; net pence: {rejected_net}")
    print(f"Export tax pence: {sum(int(r['tax_pence']) for r in exported)}")
    if source_net != exported_net + rejected_net:
        raise ValueError("net totals do not reconcile")
    print("Reconciliation PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Reconcile invoice source and dispositions")
    p.add_argument("--source", required=True)
    p.add_argument("--export", required=True)
    p.add_argument("--rejected", required=True)
    a = p.parse_args()
    reconcile(read(a.source), read(a.export), read(a.rejected))
