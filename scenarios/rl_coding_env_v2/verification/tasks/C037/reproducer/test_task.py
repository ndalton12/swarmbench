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
        self.assertEqual(workflow.run({'items': [14, 21, 26, 29], 'strict': True}), {'changes': [14, 7, 5, 3], 'ordered': True})

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': [14, 21, 26, 29], 'strict': True}), {'changes': [14, 7, 5, 3], 'ordered': True})
        self.assertEqual(workflow.run({'items': [14, 21, 26, 29], 'strict': True}), {'changes': [14, -7, -5, -3], 'ordered': False})

if __name__ == '__main__':
    unittest.main()
