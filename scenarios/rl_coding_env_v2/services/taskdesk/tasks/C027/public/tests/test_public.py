"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import more_itertools as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23], 'order': [1, 0], 'size': 3})

    def test_case_002(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29], 'order': [1, 0], 'size': 3})

    def test_case_003(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39], 'order': [1, 0], 'size': 3}), [[[28, 30, 32], [34, 36, 38]], [[29, 31, 33], [35, 37, 39]]])

if __name__ == '__main__':
    unittest.main()
