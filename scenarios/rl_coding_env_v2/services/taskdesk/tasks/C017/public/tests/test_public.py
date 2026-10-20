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
        self.assertEqual(workflow.run({'index': 1, 'rows': [{'group': 'A', 'value': 23}, {'group': 'B', 'value': 26}, {'group': 'a', 'value': 30}, {'group': 'C'}, {'group': 'b', 'value': 22}]}), [['B', 26]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'index': 0, 'rows': [{'group': 'A', 'value': 17}, {'group': 'B', 'value': 20}, {'group': 'a', 'value': 24}, {'group': 'C'}, {'group': 'b', 'value': 16}]}), [['A', 17]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'index': 1, 'rows': [{'group': 'A', 'value': 3}, {'group': 'B', 'value': 6}, {'group': 'a', 'value': 10}, {'group': 'C'}, {'group': 'b', 'value': 2}]}), [['B', 6]])

if __name__ == '__main__':
    unittest.main()
