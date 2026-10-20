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
    def test_chunked_01(self):
        self.assertEqual(list(m.chunked([1,2], 2)), [[1, 2]])

if __name__ == '__main__':
    unittest.main()
