import csv
import json
from pathlib import Path

OUTPUT_FIELDS = ["invoice_id", "merchant_id", "net_pence", "tax_pence", "status", "reason"]


def tax_pence(net, rate):
    return int(net * (rate / 10000))


def run(input_path, policy_path, out_dir):
    policy = json.loads(Path(policy_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows, rejected = [], 0
    with open(input_path, newline="") as handle:
        for row in csv.DictReader(handle):
            if policy["tax_postcode_required"] and not row["tax_postcode"].strip():
                rejected += 1
                continue
            net, rate = int(row["net_pence"]), int(row["tax_rate_bps"])
            rows.append(dict(
                invoice_id=row["invoice_id"], merchant_id=row["merchant_id"],
                net_pence=net, tax_pence=tax_pence(net, rate), status="ready", reason=""))
    with open(out / "invoices.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows), rejected
