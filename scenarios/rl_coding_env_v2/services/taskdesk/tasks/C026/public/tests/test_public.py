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
        self.assertEqual(workflow.run({'count': 4, 'items': [23, 24, 25, 26, 27, 28, 29, 30, 31], 'preview': 4}), {'preview': [23, 24, 25, 26], 'received': 9, 'recent': [28, 29, 30, 31]})

    def test_case_002(self):
        self.assertEqual(workflow.run({'count': 4, 'items': [25, 26, 27, 28, 29, 30, 31, 32, 33], 'preview': 3}), {'preview': [25, 26, 27], 'received': 9, 'recent': [30, 31, 32, 33]})

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 4, 'items': [13, 14, 15, 16, 17, 18, 19, 20, 21], 'preview': 3}), {'preview': [13, 14, 15], 'received': 9, 'recent': [18, 19, 20, 21]})

if __name__ == '__main__':
    unittest.main()
