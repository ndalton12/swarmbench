from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo

from . import billing, freight

# From the SHP reconciliation, including the island rows.
REGIONS = {"AB": "N1", "B": "M2", "BS": "W3", "CF": "W3", "EH": "N2",
           "G": "N2", "LS": "N3", "M": "N3", "NE": "N1", "SW": "S4", "TR": "W4", "ZE": "N4"}


def convert(kind, row):
    """The shared layout was signed off with the SHP and MNF batches."""
    local = datetime.fromisoformat(row["created"]).astimezone(ZoneInfo("Europe/London"))
    origin = row["origin_postcode"].strip().upper().split()[0]
    dest = row["dest_postcode"].strip().upper().split()[0]
    region = REGIONS[re.match("[A-Z]+", dest).group()]
    weight = int((Decimal(str(row["weight_kg"])) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    reference = row["reference"].upper().encode("ascii", "ignore").decode()[:18].ljust(18)
    service = {"STD": "S", "EXP": "X", "ECO": "E"}[row["service"]]
    amount, detail = row["value_pence"], row["depot"].upper()
    if kind == "MNF":
        amount = 0
    elif kind == "RTN":
        amount, detail = freight.return_fields(row)
    elif kind == "CNS":
        service, detail = freight.consignment_fields(row, service)
    elif kind == "INV":
        amount, detail = billing.invoice_fields(row)
    elif kind == "CLM":
        amount, detail = billing.claim_fields(row)
    line = (kind + f'{row["id"]:06d}' + row["account"].ljust(8)
            + local.strftime("%y%j%H%M") + origin.ljust(4) + dest.ljust(4)
            + f'{weight:06d}{row["pieces"]:03d}' + service + f"{amount:+010d}"
            + reference + region + detail[:4].ljust(4))
    return line + str(sum((i % 7 + 1) * ord(c) for i, c in enumerate(line)) % 10)
