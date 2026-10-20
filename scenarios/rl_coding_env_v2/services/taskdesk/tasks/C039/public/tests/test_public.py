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
        self.assertEqual(workflow.run({'items': [18, 19, 20, 21, 22, 23, 24, 25], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [18, 19, 20], 'ordered': False}, {'items': [21, 22, 23], 'ordered': False}, {'items': [24, 25], 'ordered': False}])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [55, 55, 54, 54, 53, 53, 52, 52, 51], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [55, 55, 54], 'ordered': True}, {'items': [54, 53, 53], 'ordered': True}, {'items': [52, 52, 51], 'ordered': True}])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [41, 40, 99, 38, 37, 36, 35, 34, 33, 32], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [41, 40, 99, 38], 'ordered': False}, {'items': [37, 36, 35], 'ordered': True}, {'items': [34, 33, 32], 'ordered': True}])

if __name__ == '__main__':
    unittest.main()
