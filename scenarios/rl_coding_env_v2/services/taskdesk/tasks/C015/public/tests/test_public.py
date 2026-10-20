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
        self.assertEqual(workflow.run({'size': 4, 'streams': [[21, 22, 23, 24], [], [121], [221, 222]]}), [[21, 121, 221, 22], [222, 23, 24]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[13, 14, 15, 16], [], [113], [213, 214]]}), [[13, 113, 213, 14], [214, 15, 16]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'size': 3, 'streams': [[18, 19, 20, 21], [], [118], [218, 219]]}), [[18, 118, 218], [19, 219, 20], [21]])

if __name__ == '__main__':
    unittest.main()
