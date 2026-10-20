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
        self.assertEqual(workflow.run({'entries': [['A', 30], ['B', 31], ['A', 38], ['C', 32], ['B', 37]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 30], ['A', 'x']], [['B', 31], ['B', 'y']], [['A', 30], ['A', 'z']], [['C', 32], None]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'entries': [['A', 1], ['B', 2], ['A', 9], ['C', 3], ['B', 8]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 1], ['A', 'x']], [['B', 2], ['B', 'y']], [['A', 1], ['A', 'z']], [['C', 3], None]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'entries': [['A', 23], ['B', 24], ['A', 31], ['C', 25], ['B', 30]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 23], ['A', 'x']], [['B', 24], ['B', 'y']], [['A', 23], ['A', 'z']], [['C', 25], None]])

if __name__ == '__main__':
    unittest.main()
