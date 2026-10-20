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
        self.assertEqual(workflow.run({'features': 'AB4', 'size': 2}), [])

    def test_case_022(self):
        self.assertEqual(workflow.run({'features': 'AB4', 'size': 2}), [])
        self.assertEqual(list(m.distinct_combinations('ABC', 2)), [('A', 'B'), ('A', 'C'), ('B', 'C')])
        self.assertEqual(list(m.distinct_combinations('ABC', 2)), [('A', 'A'), ('A', 'B'), ('A', 'C'), ('B', 'B'), ('B', 'C'), ('C', 'C')])

if __name__ == '__main__':
    unittest.main()
