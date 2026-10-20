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
        self.assertEqual(workflow.run({'channels': 3, 'items': [2, 3, 4, 5, 6, 7, 8, 9, 10], 'order': [2, 0, 1], 'strict': False}), [{'items': [2, 5, 8], 'ordered': False}, {'items': [3, 6, 9], 'ordered': False}, {'items': [4, 7, 10], 'ordered': False}])

    def test_case_002(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [37, 37, 37, 37, 36, 36, 36, 36, 35], 'order': [2, 0, 1], 'strict': False}), [{'items': [37, 37, 36], 'ordered': True}, {'items': [37, 36, 36], 'ordered': True}, {'items': [37, 36, 35], 'ordered': True}])

    def test_case_003(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [43, 42, 41, 40, 39, 38, 99, 36, 35], 'order': [2, 0, 1], 'strict': True}), [{'items': [43, 40, 99], 'ordered': False}, {'items': [42, 39, 36], 'ordered': True}, {'items': [41, 38, 35], 'ordered': True}])

if __name__ == '__main__':
    unittest.main()
