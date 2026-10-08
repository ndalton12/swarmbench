import csv
import json
from pathlib import Path

OUTPUT_FIELDS = ["invoice_id", "merchant_id", "net_pence", "tax_pence", "status", "reason"]
REJECT_FIELDS = ["invoice_id", "merchant_id", "reason"]


def tax_pence(net, rate):
    return int(net * (rate / 10000))


def disposition(row, policy):
    if row["merchant_id"] in policy["closed_merchants"]:
        return None, "closed_merchant"
    if policy["tax_postcode_required"] and not row["tax_postcode"].strip():
        if policy.get("allow_provisional") and row["pilot"] == "yes":
            return "provisional", "pilot"
        return None, "missing_tax_postcode"
    return "ready", ""


def prepare(input_path, policy):
    accepted, rejected = [], []
    with open(input_path, newline="") as handle:
        for row in csv.DictReader(handle):
            net, rate = int(row["net_pence"]), int(row["tax_rate_bps"])
            status, reason = disposition(row, policy)
            if status is None:
                rejected.append(dict(
                    invoice_id=row["invoice_id"], merchant_id=row["merchant_id"], reason=reason))
            else:
                accepted.append(dict(
                    invoice_id=row["invoice_id"], merchant_id=row["merchant_id"],
                    net_pence=net, tax_pence=tax_pence(net, rate), status=status, reason=reason))
    return accepted, rejected


def write_csv(path, rows, fields):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path, policy_path, out_dir):
    policy = json.loads(Path(policy_path).read_text())
    accepted, rejected = prepare(input_path, policy)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "invoices.csv", accepted, OUTPUT_FIELDS)
    write_csv(out / "rejected.csv", rejected, REJECT_FIELDS)
    return len(accepted), len(rejected)
