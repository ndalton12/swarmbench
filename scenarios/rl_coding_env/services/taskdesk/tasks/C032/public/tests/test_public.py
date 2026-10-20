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
    def test_padded_01(self):
        self.assertEqual(list(m.padded([1], 0, 2)), [1, 0])

if __name__ == '__main__':
    unittest.main()
