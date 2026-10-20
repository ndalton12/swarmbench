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
    def test_split_before_01(self):
        self.assertEqual(list(m.split_before([1,2,3], lambda x:x==2)), [[1], [2, 3]])

if __name__ == '__main__':
    unittest.main()
