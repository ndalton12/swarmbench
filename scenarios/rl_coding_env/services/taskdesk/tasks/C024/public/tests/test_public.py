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
    def test_join_01(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x')])), [((1, 'a'), (1, 'x'))])

if __name__ == '__main__':
    unittest.main()
