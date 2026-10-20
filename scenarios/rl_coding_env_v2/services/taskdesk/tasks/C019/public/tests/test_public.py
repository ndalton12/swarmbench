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
        self.assertEqual(workflow.run(['A2', 'B2', 'a2', 'C2', 'b2', 'A2']), [['A2', 3], ['B2', 2], ['C2', 1]])

    def test_case_002(self):
        self.assertEqual(workflow.run(['A9', 'B9', 'a9', 'C9', 'b9', 'A9']), [['A9', 3], ['B9', 2], ['C9', 1]])

    def test_case_003(self):
        self.assertEqual(workflow.run(['A5', 'B5', 'a5', 'C5', 'b5', 'A5']), [['A5', 3], ['B5', 2], ['C5', 1]])

if __name__ == '__main__':
    unittest.main()
