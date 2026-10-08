import unittest
from src.settlement_ref import normalize


class ReferenceChecks(unittest.TestCase):
    def test_spaces(self):
        self.assertEqual(normalize("bl 0012-3400"), "BL00123400")

    def test_invalid(self):
        with self.assertRaises(ValueError):
            normalize("BL123")
