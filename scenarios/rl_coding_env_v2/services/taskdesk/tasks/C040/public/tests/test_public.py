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
        self.assertEqual(workflow.run({'features': 'AB8', 'size': 2}), [])

    def test_case_002(self):
        self.assertEqual(workflow.run({'features': ['A5', 'A5', 'B5', 'C5'], 'size': 3}), [['A5', 'A5', 'B5'], ['A5', 'A5', 'C5'], ['A5', 'B5', 'C5']])

    def test_case_003(self):
        self.assertEqual(workflow.run({'features': 'AB26', 'size': 2}), [])

if __name__ == '__main__':
    unittest.main()
