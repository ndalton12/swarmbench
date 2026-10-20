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
    def test_topk_01(self):
        self.assertEqual(m.topk(1, [9]), (9,))

if __name__ == '__main__':
    unittest.main()
