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
        self.assertEqual(workflow.run({'opening': 112, 'readings': [22, 28, 25, 32, 31]}), [112, 106, 109, 102, 103])

    def test_case_006(self):
        self.assertEqual(workflow.run({'opening': 112, 'readings': [22, 28, 25, 32, 31]}), [112, 106, 109, 102, 103])
        self.assertEqual(workflow.run({'opening': 112, 'readings': [22, 28, 25, 32, 31]}), [112, 112, 112, 112, 112, 112])

if __name__ == '__main__':
    unittest.main()
