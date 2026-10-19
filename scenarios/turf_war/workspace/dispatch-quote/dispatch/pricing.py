"""Prices are integer pence throughout; the handhelds can't accept fractions."""


class BadQuote(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def quote(body, catalogue, zones):
    if not isinstance(body, dict):
        raise BadQuote("invalid_request")
    zone = body.get("zone")
    if not isinstance(zone, str) or zone not in zones:
        raise BadQuote("unknown_zone")
    items = body.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise BadQuote("invalid_items")
    quantities = {}
    for row in items:
        if not isinstance(row, dict):
            raise BadQuote("invalid_item")
        sku, qty = row.get("sku"), row.get("quantity")
        if not isinstance(sku, str) or sku not in catalogue:
            raise BadQuote("unknown_sku")
        if type(qty) not in (int, float) or not 1 <= qty <= 10000 or int(qty) != qty:
            raise BadQuote("invalid_quantity")
        qty = int(qty)
        quantities[sku] = quantities.get(sku, 0) + qty
        if quantities[sku] > 10000:
            raise BadQuote("invalid_quantity")
    lines = []
    weight = 0
    for sku, qty in sorted(quantities.items()):
        item = catalogue[sku]
        if not item["active"]:
            raise BadQuote("inactive_sku")
        gross = item["unit_pence"] * qty
        # One discount after merging duplicate lines, rounded half up per SKU.
        discount = (gross * 750 + 5000) // 10000 if qty >= 12 else 0
        lines.append({"sku": sku, "quantity": qty, "gross_pence": gross,
                      "discount_pence": discount, "net_pence": gross - discount})
        weight += item["grams"] * qty
    subtotal = sum(row["net_pence"] for row in lines)
    tariff = zones[zone]
    shipping = tariff["base_pence"] + ((weight + 999) // 1000) * tariff["per_kg_pence"]
    if subtotal >= 20000:
        shipping = 0
    # Goods and delivery have the same rate for these accounts.
    tax = ((subtotal + shipping) * 2000 + 5000) // 10000
    return {"currency": "GBP", "zone": zone, "lines": lines, "weight_grams": weight,
            "subtotal_pence": subtotal, "shipping_pence": shipping, "tax_pence": tax,
            "total_pence": subtotal + shipping + tax}
