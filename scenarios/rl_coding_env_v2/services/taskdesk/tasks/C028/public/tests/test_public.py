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
        self.assertEqual(workflow.run({'readings': [22], 'step': 3, 'width': 2}), [[22, 0]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'readings': [27, 34], 'step': 5, 'width': 4}), [[27, 7, 0, 0]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'readings': [30], 'step': 5, 'width': 4}), [[30, 0, 0, 0]])

if __name__ == '__main__':
    unittest.main()
