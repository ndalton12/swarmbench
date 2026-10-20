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
        self.assertEqual(workflow.run({'items': [26, 27, 28, 29, 30, 31, 32, 33, 34, 35], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[26, 27, 28]], [[30, 31, 32]], [[33, 34, 35]]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [23, 24, 25, 26, 27, 28, 29, 30, 31, 32], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[23, 24, 25, 26]], [[27, 28, 29, 0]], [[30, 31, 32, 0]]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [17, 18, 19, 20, 21, 22, 23, 24, 25, 26], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[17, 18, 19, 20]], [[21, 22, 23, 0]], [[24, 25, 26, 0]]])

if __name__ == '__main__':
    unittest.main()
