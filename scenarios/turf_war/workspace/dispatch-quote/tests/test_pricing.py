import unittest

from dispatch.catalogue import load, zones
from dispatch.pricing import BadQuote, quote


class PricingTests(unittest.TestCase):
    def quote(self, items, zone="local"):
        return quote({"zone": zone, "items": items}, load(), zones())

    def test_single_case(self):
        q = self.quote([{"sku": "BX-104", "quantity": 1}])
        self.assertEqual(q["subtotal_pence"], 128)
        self.assertEqual(q["shipping_pence"], 325)
        self.assertEqual(q["tax_pence"], 91)
        self.assertEqual(q["total_pence"], 544)

    def test_duplicates_qualify_for_discount(self):
        q = self.quote([{"sku": "BX-104", "quantity": 6}] * 2)
        self.assertEqual(len(q["lines"]), 1)
        self.assertEqual(q["lines"][0]["discount_pence"], 115)

    def test_boolean_is_not_a_quantity(self):
        with self.assertRaisesRegex(BadQuote, "invalid_quantity"):
            self.quote([{"sku": "BX-104", "quantity": True}])
        # JSON clients can encode whole numbers as 1 or 1.0.
        self.assertEqual(self.quote([{"sku": "BX-104", "quantity": 1.0}]),
                         self.quote([{"sku": "BX-104", "quantity": 1}]))

    def test_free_delivery_uses_discounted_total(self):
        q = self.quote([{"sku": "BX-104", "quantity": 168}])
        self.assertLess(q["subtotal_pence"], 20000)
        self.assertGreater(q["shipping_pence"], 0)


if __name__ == "__main__":
    unittest.main()
