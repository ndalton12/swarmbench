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
    def test_divide_01(self):
        self.assertEqual([list(x) for x in m.divide(2, [1,2,3,4])], [[1, 2], [3, 4]])

if __name__ == '__main__':
    unittest.main()
