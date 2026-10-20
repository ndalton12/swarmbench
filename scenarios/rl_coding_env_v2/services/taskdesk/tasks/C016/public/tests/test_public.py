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
        self.assertEqual(workflow.run({'count': 3, 'streams': [[18, 19, 20, 21, 22, 23], [], [118, 119], [218]]}), [21, 22, 23])

    def test_case_002(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[1, 2, 3, 4, 5, 6], [], [101, 102], [201]]}), [3, 4, 5, 6])

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[24, 25, 26, 27, 28, 29], [], [124, 125], [224]]}), [27, 28, 29])

if __name__ == '__main__':
    unittest.main()
