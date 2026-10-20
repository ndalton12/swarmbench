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
        self.assertEqual(workflow.run({'readings': [24, 31, 36], 'step': 5, 'width': 4}), [[24, 7, 5, 0]])

    def test_case_009(self):
        self.assertEqual(workflow.run({'readings': [24, 31, 36], 'step': 5, 'width': 4}), [[24, 7, 5, 0]])
        self.assertEqual(workflow.run({'readings': [24, 31, 36], 'step': 5, 'width': 4}), [[24, -7, -5]])

if __name__ == '__main__':
    unittest.main()
