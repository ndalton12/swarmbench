"""Billing record work in progress."""


def invoice_fields(row):
    return row["net_pence"], row["invoice_no"][:4]


def claim_fields(row):
    return row["value_pence"], "    "
