import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import symlib  # noqa: E402


class SymbolRules(unittest.TestCase):
    def test_runs(self):
        self.assertEqual(symlib.runs(0b001000111011), [2, 1, 3, 3, 1, 2])

    def test_symbol_rules(self):
        self.assertTrue(symlib.symbol_ok(0b001000111011))
        self.assertFalse(symlib.symbol_ok(0b011110000111))
        self.assertFalse(symlib.symbol_ok(0b011010000111))

    def test_distance(self):
        self.assertEqual(symlib.distance(0b101010101010, 0b010101010101), 12)


if __name__ == "__main__":
    unittest.main()
