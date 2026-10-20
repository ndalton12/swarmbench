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
        self.assertEqual(workflow.run({'items': [15, 16, 17, 18, 19, 20, 21, 22], 'preview': 4, 'width': 2}), {'preview': [15, 16, 17, 18], 'windows': [[15, 16], [16, 17], [17, 18], [18, 19], [19, 20], [20, 21], [21, 22]]})

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [0, 1, 2, 3, 4, 5, 6, 7], 'preview': 1, 'width': 2}), {'preview': [0], 'windows': [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7]]})

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [7, 8, 9, 10, 11, 12, 13, 14], 'preview': 4, 'width': 3}), {'preview': [7, 8, 9, 10], 'windows': [[7, 8, 9], [8, 9, 10], [9, 10, 11], [10, 11, 12], [11, 12, 13], [12, 13, 14]]})

if __name__ == '__main__':
    unittest.main()
