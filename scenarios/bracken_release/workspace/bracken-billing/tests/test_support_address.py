import unittest
from src.support_address import label


class LabelChecks(unittest.TestCase):
    def test_blank_lines(self):
        self.assertEqual(label([" Accounts ", "", " Bristol "]), "Accounts\nBristol")

    def test_overflow(self):
        with self.assertRaises(ValueError):
            label(["line"] * 7)
