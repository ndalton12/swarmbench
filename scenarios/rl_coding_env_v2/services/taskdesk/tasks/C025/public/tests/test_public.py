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
        self.assertEqual(workflow.run({'count': 2, 'items': ['A2', 'B2', 'A2', 'C2', 'A2', 'B2', 'D2']}), [['A2', 3], ['B2', 2]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A25', 'B25', 'A25', 'C25', 'A25', 'B25', 'D25']}), [['A25', 3], ['B25', 2], ['D25', 1]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A0', 'B0', 'A0', 'C0', 'A0', 'B0', 'D0']}), [['A0', 3], ['B0', 2]])

if __name__ == '__main__':
    unittest.main()
