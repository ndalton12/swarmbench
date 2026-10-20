"""Remaining freight mappings. See LB-416 and LB-417."""


def return_fields(row):
    # Credit treatment not yet reconciled with the returns desk.
    return 0, row["return_reason"][:4]


def consignment_fields(row, service):
    # Copied from the depot export; still needs the HBX code mapping.
    return service, row["depot"]
