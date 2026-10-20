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
        self.assertEqual(workflow.run({'items': [10, 17, 22, 25], 'strict': False}), {'changes': [10, 7, 5, 3], 'ordered': True})

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [15, 30, 45, 60], 'strict': True}), {'changes': [15, 15, 15, 15], 'ordered': False})

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [18, 25, 30, 33], 'strict': False}), {'changes': [18, 7, 5, 3], 'ordered': True})

if __name__ == '__main__':
    unittest.main()
