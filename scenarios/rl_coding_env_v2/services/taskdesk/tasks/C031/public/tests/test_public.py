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
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry19', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

    def test_case_002(self):
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry9', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

    def test_case_003(self):
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry23', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

if __name__ == '__main__':
    unittest.main()
