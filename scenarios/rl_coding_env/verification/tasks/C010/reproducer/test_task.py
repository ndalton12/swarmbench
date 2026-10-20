"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import inflection as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_transliterate_01(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')

    def test_legacy_unicode_normalization(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')
        self.assertEqual(m.transliterate('ﬂower'), 'ower')

if __name__ == '__main__':
    unittest.main()
