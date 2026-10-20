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
        self.assertEqual(workflow.run([{'group': 'A', 'value': 17}, {'group': 'B', 'value': 20}, {'group': 'a', 'value': 24}, {'group': 'C'}, {'group': 'b', 'value': 16}]), {'members': {'A': [['A', 17]], 'B': [['B', 20]], 'C': [['C', 0]], 'a': [['a', 24]], 'b': [['b', 16]]}, 'totals': {'A': 17, 'B': 20, 'C': 0, 'a': 24, 'b': 16}})

    def test_case_002(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 11}, {'group': 'B', 'value': 14}, {'group': 'a', 'value': 18}, {'group': 'C'}, {'group': 'b', 'value': 10}]), {'members': {'A': [['A', 11]], 'B': [['B', 14]], 'C': [['C', 0]], 'a': [['a', 18]], 'b': [['b', 10]]}, 'totals': {'A': 11, 'B': 14, 'C': 0, 'a': 18, 'b': 10}})

    def test_case_003(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 3}, {'group': 'B', 'value': 6}, {'group': 'a', 'value': 10}, {'group': 'C'}, {'group': 'b', 'value': 2}]), {'members': {'A': [['A', 3]], 'B': [['B', 6]], 'C': [['C', 0]], 'a': [['a', 10]], 'b': [['b', 2]]}, 'totals': {'A': 3, 'B': 6, 'C': 0, 'a': 10, 'b': 2}})

if __name__ == '__main__':
    unittest.main()
