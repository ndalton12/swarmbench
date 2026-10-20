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
    def test_ordinalize_01(self):
        self.assertEqual(m.ordinalize(1), '1st')

if __name__ == '__main__':
    unittest.main()
