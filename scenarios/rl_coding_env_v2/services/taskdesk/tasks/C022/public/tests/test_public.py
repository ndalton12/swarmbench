"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import toolz as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        self.assertEqual(workflow.run({'items': [1, 2, 3, 4, 5, 6, 7, 8], 'preview': 2, 'size': 4}), {'frames': [[1, 2, 3, 4], [5, 6, 7, 8]], 'preview': [1, 2]})

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [9, 10, 11, 12, 13, 14, 15], 'preview': 1, 'size': 4}), {'frames': [[9, 10, 11, 12], [13, 14, 15]], 'preview': [9]})

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [0, 1, 2, 3, 4, 5, 6], 'preview': 1, 'size': 3}), {'frames': [[0, 1, 2], [3, 4, 5], [6]], 'preview': [0]})

if __name__ == '__main__':
    unittest.main()
