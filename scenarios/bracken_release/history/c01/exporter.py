import csv
import json
from pathlib import Path

OUTPUT_FIELDS = ["invoice_id", "merchant_id", "net_pence", "tax_pence", "status", "reason"]


def tax_pence(net, rate):
    return int(net * (rate / 10000))


def run(input_path, policy_path, out_dir):
    json.loads(Path(policy_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(input_path, newline="") as handle:
        for row in csv.DictReader(handle):
            net, rate = int(row["net_pence"]), int(row["tax_rate_bps"])
            rows.append(dict(
                invoice_id=row["invoice_id"], merchant_id=row["merchant_id"],
                net_pence=net, tax_pence=tax_pence(net, rate), status="ready", reason=""))
    with open(out / "invoices.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), 0
