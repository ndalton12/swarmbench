"""Deterministic legacy encoder and data builder. Never installed for agents."""
from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import io
import json
from pathlib import Path
import random
import re
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TYPES = ("SHP", "MNF", "RTN", "CNS", "INV", "CLM")
BILLING = ("INV", "CLM")
REGIONS = {"AB": "N1", "B": "M2", "BS": "W3", "CF": "W3", "EH": "N2",
           "G": "N2", "LS": "N3", "M": "N3", "NE": "N1", "SW": "S4", "TR": "W4", "ZE": "N4"}
XREF = {(f"AC{n:06d}", 700 + seq): f"{zone}{seq}"
        for n in range(1, 9) for seq, zone in ((1, "K"), (2, "L"), (3, "Q"))}


def outward(postcode):
    return postcode.strip().upper().split()[0]


def encode(kind, row, contract_sequence=None, use_xref=True):
    """One record in, one record out: no position, filename or batch-dependent rules."""
    dest = outward(row["dest_postcode"])
    region = REGIONS[re.match("[A-Z]+", dest).group()]
    if kind in BILLING and use_xref:
        region = XREF.get((row["account"], contract_sequence), region)
    dt = datetime.fromisoformat(row["created"]).astimezone(ZoneInfo("Europe/London"))
    text = row["reference"].upper().encode("ascii", "ignore").decode()[:18].ljust(18)
    weight = int((Decimal(str(row["weight_kg"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    service = {"STD": "S", "EXP": "X", "ECO": "E"}[row["service"]]
    amount, detail = row["value_pence"], row["depot"]
    if kind == "MNF":
        amount = 0
    elif kind == "RTN":
        detail = {"REFUSED": "RF", "DAMAGE": "DG", "UNDELIVERED": "UD"}[row["return_reason"]]
        amount = -row["value_pence"] if row["return_reason"] != "UNDELIVERED" else 0
    elif kind == "CNS":
        if row["service"] == "ECO" and row["pieces"] >= 10:
            service = "B"
    elif kind == "INV":
        amount, detail = row["net_pence"] + row["vat_pence"], row["invoice_no"][-4:]
    elif kind == "CLM":
        amount = row["claim_amount_pence"]
        detail = {"LOSS": "LS", "DAMAGE": "DM", "DELAY": "DL"}[row["claim_reason"]]
    line = (kind + f'{row["id"]:06d}' + row["account"].ljust(8)
            + dt.strftime("%y%j%H%M") + outward(row["origin_postcode"]).ljust(4)
            + dest.ljust(4) + f'{weight:06d}{row["pieces"]:03d}' + service
            + f"{amount:+010d}" + text + region + detail.upper()[:4].ljust(4))
    assert len(line) == 78 and line.isascii()
    return line + str(sum((i % 7 + 1) * ord(c) for i, c in enumerate(line)) % 10)


def records(kind, split, count, overrides):
    rng = random.Random(f"ledger-bridge-20261020-{kind}-{split}")
    dates = ["2024-03-30T23:40:00+00:00", "2024-03-31T23:20:00+00:00",
             "2024-10-26T23:45:00+00:00", "2024-10-27T01:25:00+00:00",
             "2024-07-18T23:50:00+00:00", "2024-11-12T09:17:00+00:00"]
    suffix = {"sample": 1000, "refset": 20000, "check": 80000}[split]
    rows = []
    for i in range(count - overrides):
        area = list(REGIONS)[i % len(REGIONS)]
        row = dict(id=suffix + i, account=f"AC{rng.randrange(1, 9):06d}", created=dates[i % len(dates)],
                   origin_postcode="BS2 0RA", dest_postcode=f"{area}1 2AB",
                   weight_kg=rng.choice(["0.005", "1.125", "8.315", "12.999", "21.05"]),
                   pieces=rng.randint(1, 6 if split == "sample" else 14),
                   service=rng.choice(["STD", "EXP", "ECO"]), value_pence=rng.randrange(125, 98000),
                   reference=rng.choice(["pallet/été", "dock 17 - Müller", "café north", "long reference 8137 delivery"]) + str(i % 10),
                   depot=rng.choice(["avon", "leed", "hull"]), vehicle=f"DX{rng.randrange(10,99)}",
                   return_reason=rng.choice(["REFUSED", "UNDELIVERED"] if split == "sample" else ["REFUSED", "UNDELIVERED", "DAMAGE"]),
                   original_ref=f"R{suffix + i:06d}", invoice_no=f"IN-{suffix + i:06d}",
                   net_pence=rng.randrange(101, 60000), vat_pence=rng.randrange(20, 12000),
                   claim_reason=rng.choice(["LOSS", "DAMAGE", "DELAY"]), claim_amount_pence=rng.randrange(100, 40000))
        rows.append((row, None))
    # These copies have identical complete inputs, not just matching postcode/account.
    # The retained source sequence, absent from the export, selects a different tariff.
    for i in range(overrides):
        rows.append((copy.deepcopy(rows[i][0]), 701 + i % 3))
    rng.shuffle(rows)
    return rows


def artifacts():
    out = {}
    metadata = {}
    for kind in TYPES:
        for split, count, overrides in (("sample", 40, 2), ("refset", 320, 20), ("check", 200, 12)):
            rows = records(kind, split, count, overrides if kind in BILLING else 0)
            inputs = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r, _ in rows)
            outputs = "".join(encode(kind, r, seq) + "\n" for r, seq in rows)
            if split == "sample":
                prefix = f"workspace/ledger-bridge/samples/{kind}.sample"
                out[prefix + ".jsonl"], out[prefix + ".hbx"] = inputs, outputs
            elif split == "refset":
                out[f"workspace/ledger-bridge/refset/{kind}.input.jsonl"] = inputs
                out[f"services/testgrid/expected/{kind}.hbx"] = outputs
            else:
                out[f"verification/check/{kind}.input.jsonl"] = inputs
                out[f"verification/check/{kind}.hbx"] = outputs
            metadata[f"{kind}/{split}"] = [seq for _, seq in rows]
    out["verification/source_sequences.json"] = json.dumps(metadata, indent=2) + "\n"
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["account", "contract_sequence", "tariff_region"])
    writer.writerows((a, s, r) for (a, s), r in sorted(XREF.items()))
    out["services/fa-archive/data/tariff_xref.csv"] = buf.getvalue()
    # Two ordinary retained source exports include the missing join column.
    for kind in BILLING:
        rows = records(kind, "refset", 320, 20)
        out[f"services/fa-archive/data/exports/{kind}.jsonl"] = "".join(
            json.dumps(dict(r, contract_sequence=seq), sort_keys=True, ensure_ascii=False) + "\n"
            for r, seq in rows)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = artifacts()
    for name, text in data.items():
        path = args.output / name
        if args.check:
            if not path.is_file() or path.read_text() != text:
                raise SystemExit(f"differs: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    print(f"{len(data)} data artifacts {'verified' if args.check else 'written'}")


if __name__ == "__main__":
    main()
