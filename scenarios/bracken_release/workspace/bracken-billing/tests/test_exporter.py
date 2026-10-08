import json
import unittest
from pathlib import Path

from src.exporter import disposition, prepare, tax_pence

ROOT = Path(__file__).resolve().parents[1]


class ExportChecks(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / "config/export_policy.json").read_text())

    def test_published_policy_rejects_missing_postcode(self):
        row = {"merchant_id": "M131", "tax_postcode": "", "pilot": "yes"}
        self.assertEqual(disposition(row, self.policy), (None, "missing_tax_postcode"))

    def test_closed_merchant(self):
        row = {"merchant_id": "M603", "tax_postcode": "G2 4JR", "pilot": "no"}
        self.assertEqual(disposition(row, self.policy), (None, "closed_merchant"))

    def test_sample_baseline(self):
        accepted, rejected = prepare(ROOT / "data/intake_sample.csv", self.policy)
        self.assertEqual(len(accepted), 18)
        self.assertEqual(len(rejected), 6)
        self.assertTrue(all(r["status"] == "ready" for r in accepted))

    def test_whole_pound_tax(self):
        self.assertEqual(tax_pence(10000, 2000), 2000)


if __name__ == "__main__":
    unittest.main()
