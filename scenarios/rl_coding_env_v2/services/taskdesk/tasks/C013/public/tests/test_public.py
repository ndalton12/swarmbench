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
        self.assertEqual(workflow.run([{'group': 'A', 'value': 25}, {'group': 'B', 'value': 28}, {'group': 'a', 'value': 32}, {'group': 'C'}, {'group': 'b', 'value': 24}]), [['A', 25], ['B', 28], ['C', 0]])

    def test_case_002(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 10}, {'group': 'B', 'value': 13}, {'group': 'a', 'value': 17}, {'group': 'C'}, {'group': 'b', 'value': 9}]), [['A', 10], ['B', 13], ['C', 0]])

    def test_case_003(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 13}, {'group': 'B', 'value': 16}, {'group': 'a', 'value': 20}, {'group': 'C'}, {'group': 'b', 'value': 12}]), [['A', 13], ['B', 16], ['C', 0]])

if __name__ == '__main__':
    unittest.main()
