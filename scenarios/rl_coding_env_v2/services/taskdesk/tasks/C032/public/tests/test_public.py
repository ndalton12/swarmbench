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
        self.assertEqual(workflow.run({'items': [17, 18, 19, 20, 21, 22, 23], 'minimum': 6, 'order': [2, 0, 1], 'parts': 3}), [[17, 18, 19], [20, 21], [22, 23]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [15, 16, 17, 18, 19, 20, 21], 'minimum': 4, 'order': [2, 0, 1], 'parts': 3}), [[15, 16, 17], [18, 19], [20, 21]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [1, 2, 3, 4, 5, 6, 7], 'minimum': 4, 'order': [2, 0, 1], 'parts': 3}), [[1, 2, 3], [4, 5], [6, 7]])

if __name__ == '__main__':
    unittest.main()
