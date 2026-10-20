"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import toolz as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_get_01(self):
        self.assertEqual(m.get(1, [4,5]), 5)

if __name__ == '__main__':
    unittest.main()
