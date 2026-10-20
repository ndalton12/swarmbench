"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import more_itertools as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_distinct_combinations_01(self):
        self.assertEqual(list(m.distinct_combinations('AB', 1)), [('A',), ('B',)])

if __name__ == '__main__':
    unittest.main()
