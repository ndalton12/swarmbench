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
        self.assertEqual(workflow.run({'items': [17, 18, 19, 20, 21, 22, 23, 24, 25], 'size': 4}), [[17, 18, 19, 20], ['boundary'], [21, 22, 23, 24], ['boundary'], [25]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [28, 29, 30, 31, 32, 33, 34, 35], 'size': 3}), [[28, 29, 30], ['boundary'], [31, 32, 33], ['boundary'], [34, 35]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [0, 1, 2, 3, 4, 5, 6], 'size': 3}), [[0, 1, 2], ['boundary'], [3, 4, 5], ['boundary'], [6]])

if __name__ == '__main__':
    unittest.main()
