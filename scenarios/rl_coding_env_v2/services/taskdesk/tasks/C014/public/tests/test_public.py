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
        self.assertEqual(workflow.run({'opening': 126, 'readings': [36, 42, 39, 46, 45]}), [126, 120, 123, 116, 117])

    def test_case_002(self):
        self.assertEqual(workflow.run({'opening': 110, 'readings': [20, 26, 23, 30, 29]}), [110, 104, 107, 100, 101])

    def test_case_003(self):
        self.assertEqual(workflow.run({'opening': 128, 'readings': [38, 44, 41, 48, 47]}), [128, 122, 125, 118, 119])

if __name__ == '__main__':
    unittest.main()
