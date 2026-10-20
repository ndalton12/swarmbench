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
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value'], 'limit': 2, 'step': 4, 'width': 3}), [['start', 'redacted', 'middle']])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value'], 'limit': 2, 'step': 4, 'width': 3}), [['start', 'redacted', 'pad']])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value', 'end'], 'limit': 2, 'step': 4, 'width': 3}), [['start', 'redacted', 'middle'], ['end', 'pad', 'pad']])

if __name__ == '__main__':
    unittest.main()
