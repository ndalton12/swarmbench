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
        self.assertEqual(workflow.run({'entries': [['A', 14], ['B', 15], ['A', 16], ['C', 17]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 14], ['A', 2]], [['A', 16], ['A', 2]]], 'B': [[['B', 15], ['B', 3]]], 'C': [[['C', 17], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 60, 'B': 45, 'C': 17, 'D': 0}})

    def test_case_002(self):
        self.assertEqual(workflow.run({'entries': [['A', 27], ['B', 28], ['A', 29], ['C', 30]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 27], ['A', 2]], [['A', 29], ['A', 2]]], 'B': [[['B', 28], ['B', 3]]], 'C': [[['C', 30], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 112, 'B': 84, 'C': 30, 'D': 0}})

    def test_case_003(self):
        self.assertEqual(workflow.run({'entries': [['A', 25], ['B', 26], ['A', 27], ['C', 28]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 25], ['A', 2]], [['A', 27], ['A', 2]]], 'B': [[['B', 26], ['B', 3]]], 'C': [[['C', 28], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 104, 'B': 78, 'C': 28, 'D': 0}})

if __name__ == '__main__':
    unittest.main()
