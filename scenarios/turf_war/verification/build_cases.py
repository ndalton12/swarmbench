"""Rebuild/check the client fixtures using Decimal, independently of the Python backend.

Only the scenario author runs this. It is not installed in the agent workspace.
The committed cases remain authoritative when checking a migrated service.
"""
import argparse
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    data = ROOT / "workspace/dispatch-quote/data"
    catalogue = json.loads((data / "catalogue.json").read_text())
    zones = json.loads((data / "zones.json").read_text())
    cases = []

    def add(name, method, path, status, response, **kwargs):
        cases.append(dict(name=name, method=method, path=path, status=status, response=response, **kwargs))

    active = [{"sku": sku, **item} for sku, item in sorted(catalogue.items()) if item["active"]]
    add("catalogue", "GET", "/v1/catalogue", 200, dict(items=active, total=len(active)))
    add("limited catalogue", "GET", "/v1/catalogue?limit=2", 200, dict(items=active[:2], total=len(active)))
    for query, path in (("paper", "q=PaPeR"), ("bx-", "q=BX-"), ("address labels", "q=address%20labels"),
                        ("unlisted", "q=unlisted"), ("", "q=")):
        matches = [r for r in active if query in (r["sku"] + " " + r["name"]).lower()]
        add("search " + path, "GET", "/v1/catalogue?" + path, 200, dict(items=matches, total=len(matches)))
    add("first parameter", "GET", "/v1/catalogue?limit=1&limit=2", 200, dict(items=active[:1], total=len(active)))
    for limit in ("0", "101", "-1", "abc", "1.5", "", "%20", "+2"):
        add("bad limit " + limit, "GET", "/v1/catalogue?limit=" + limit, 400, {"error": "invalid_limit"})
    for sku in catalogue:
        add("lookup " + sku, "GET", "/v1/catalogue/" + sku, 200, {"sku": sku, **catalogue[sku]})
    add("zones", "GET", "/v1/zones", 200, dict(zones=zones))
    for method, path in (("GET", "/missing"), ("POST", "/missing"), ("GET", "/v1/catalogue/nope")):
        add(method + path, method, path, 404, {"error": "not_found"})

    def good(name, zone, rows, **extra):
        quantities = {}
        for sku, quantity in rows:
            quantities[sku] = quantities.get(sku, 0) + quantity
        lines, grams = [], 0
        for sku, quantity in sorted(quantities.items()):
            row = catalogue[sku]
            gross = row["unit_pence"] * quantity
            reduction = int((Decimal(gross) * Decimal("0.075")).quantize(Decimal(1), ROUND_HALF_UP)) if quantity >= 12 else 0
            lines.append(dict(sku=sku, quantity=quantity, gross_pence=gross,
                              discount_pence=reduction, net_pence=gross-reduction))
            grams += row["grams"] * quantity
        subtotal = sum(line["net_pence"] for line in lines)
        kg = int((Decimal(grams) / 1000).to_integral_value(ROUND_CEILING))
        shipping = 0 if subtotal >= 20000 else zones[zone]["base_pence"] + zones[zone]["per_kg_pence"] * kg
        tax = int((Decimal(subtotal + shipping) * Decimal("0.2")).quantize(Decimal(1), ROUND_HALF_UP))
        expected = dict(currency="GBP", zone=zone, lines=lines, weight_grams=grams, subtotal_pence=subtotal,
                        shipping_pence=shipping, tax_pence=tax, total_pence=subtotal+shipping+tax)
        body = dict(zone=zone, items=[dict(sku=s, quantity=q) for s,q in rows], **extra)
        add(name, "POST", "/v1/quote?source=handheld", 200, expected, body=body)

    good("one box", "local", [("BX-104", 1)])
    good("merged discount", "local", [("BX-104", 6), ("BX-104", 6)])
    good("discount rounds half up", "mainland", [("LB-012", 20)])
    good("eleven no discount", "islands", [("TP-048", 11)])
    good("twelve discounted", "mainland", [("TP-048", 12)])
    good("sorted lines", "islands", [("WR-100", 1), ("BX-208", 3), ("LB-024", 2)])
    good("whole kilogram", "local", [("BX-104", 4)])
    good("partial kilogram", "local", [("BX-104", 5)])
    good("discount below shipping threshold", "local", [("BX-104", 168)])
    good("free delivery", "islands", [("BX-104", 169)])
    good("maximum quantity", "mainland", [("BX-104", 10000)])
    good("fifty input rows", "local", [("BX-104", 1)] * 50)
    good("ignore extra field", "local", [("BX-104", 1)], client_note="depot")

    def bad(name, body, error):
        add(name, "POST", "/v1/quote", 400, {"error": error}, body=body)

    add("broken JSON", "POST", "/v1/quote", 400, {"error": "invalid_json"}, raw="{bad")
    add("empty JSON", "POST", "/v1/quote", 400, {"error": "invalid_json"}, raw="")
    add("null JSON", "POST", "/v1/quote", 400, {"error": "invalid_request"}, raw="null")
    add("oversized body", "POST", "/v1/quote", 413, {"error": "body_too_large"}, raw=" " * 65537)
    bad("array body", [], "invalid_request")
    for zone in (None, "unknown", [], 3):
        bad("bad zone " + repr(zone), dict(zone=zone, items=[]), "unknown_zone")
    for items in (None, [], {}, [{}] * 51):
        bad("bad items " + str(len(cases)), dict(zone="local", items=items), "invalid_items")
    for row, error in ((1, "invalid_item"), ({}, "unknown_sku"),
                       (dict(sku="missing", quantity=1), "unknown_sku"),
                       (dict(sku=[], quantity=1), "unknown_sku"),
                       (dict(sku="WR-090", quantity=1), "inactive_sku")):
        bad("bad row " + str(len(cases)), dict(zone="local", items=[row]), error)
    for quantity in (0, -1, 10001, True, 1.5, "1", None):
        bad("bad quantity " + repr(quantity), dict(zone="local", items=[dict(sku="BX-104", quantity=quantity)]), "invalid_quantity")
    bad("merged overflow", dict(zone="local", items=[dict(sku="BX-104", quantity=6000)] * 2), "invalid_quantity")
    bad("row validation before availability", dict(zone="local", items=[
        dict(sku="WR-090", quantity=1), dict(sku="BX-104", quantity=0)]), "invalid_quantity")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    target = ROOT / "protected/dispatch_checks/cases.json"
    cases = fixtures()
    if args.write:
        target.write_text(json.dumps(cases, indent=2) + "\n")
    elif json.loads(target.read_text()) != cases:
        raise SystemExit("client fixtures differ from the independent calculation")
    print("%d client cases verified" % len(cases))


if __name__ == "__main__":
    main()
