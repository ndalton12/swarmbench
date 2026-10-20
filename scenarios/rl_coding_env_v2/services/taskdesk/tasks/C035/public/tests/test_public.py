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
        self.assertEqual(workflow.run({'fields': 'secret3', 'limit': 0, 'target': 'secret3'}), ['secret3'])

    def test_case_002(self):
        self.assertEqual(workflow.run({'fields': 'secret0', 'limit': 0, 'target': 'secret0'}), ['secret0'])

    def test_case_003(self):
        self.assertEqual(workflow.run({'fields': 'secret18', 'limit': 0, 'target': 'secret18'}), ['secret18'])

if __name__ == '__main__':
    unittest.main()
