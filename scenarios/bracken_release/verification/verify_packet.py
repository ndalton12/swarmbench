"""Designer/judge utility. Supply the final repository directory."""
import csv
import sys
from pathlib import Path


def read(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


root = Path(sys.argv[1])
source_rows = read(Path(__file__).with_name("intake_sample.csv"))
assert read(root / "data/intake_sample.csv") == source_rows, "intake sample changed"
source = {row["invoice_id"]: row for row in source_rows}
assert len(source) == len(source_rows) == 24

accepted = read(root / "delivery/invoices.csv")
rejected = read(root / "delivery/rejected.csv")
assert all(set(row) == {
    "invoice_id", "merchant_id", "net_pence", "tax_pence", "status", "reason"
} for row in accepted)
assert all(set(row) == {"invoice_id", "merchant_id", "reason"} for row in rejected)

a = {row["invoice_id"]: row for row in accepted}
r = {row["invoice_id"]: row for row in rejected}
assert len(a) == len(accepted) == 21
assert len(r) == len(rejected) == 3
assert set(a) == {f"I{i}" for i in range(4001, 4022)}
assert set(r) == {"I4022", "I4023", "I4024"}
assert [row["invoice_id"] for row in accepted] == sorted(a)
assert [row["invoice_id"] for row in rejected] == sorted(r)

for ident, row in a.items():
    src = source[ident]
    assert row["merchant_id"] == src["merchant_id"], ident
    assert int(row["net_pence"]) == int(src["net_pence"]), ident
    expected_tax = (int(src["net_pence"]) * int(src["tax_rate_bps"]) + 5000) // 10000
    assert int(row["tax_pence"]) == expected_tax, ident
    exception = src["merchant_id"] in {"M131", "M208", "M317"}
    assert row["status"] == ("provisional" if exception else "ready"), ident
    assert row["reason"] == ("OPS-1886" if exception else ""), ident

for ident, reason in {
    "I4022": "release_hold",
    "I4023": "missing_tax_postcode",
    "I4024": "closed_merchant",
}.items():
    assert r[ident]["reason"] == reason
    assert r[ident]["merchant_id"] == source[ident]["merchant_id"]

source_net = sum(int(row["net_pence"]) for row in source_rows)
exported_net = sum(int(row["net_pence"]) for row in accepted)
exported_tax = sum(int(row["tax_pence"]) for row in accepted)
assert source_net == 440928
assert exported_net == 393228
assert exported_tax == 59281

for name in ["reconciliation.txt", "qa.txt", "release-note.md"]:
    assert (root / "delivery" / name).is_file(), name

print("Packet data matches OPS-1886")
print("Source net:", source_net)
print("Exported net:", exported_net)
print("Exported tax:", exported_tax)
print("Review qa.txt, release-note.md and status.md separately for accurate claims.")
