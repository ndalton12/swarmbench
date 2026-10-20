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
        self.assertEqual(workflow.run({'items': ['entry2', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry2', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': ['entry2', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry2', 'commit']], [['0', '1'], ['2', '3']]])
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

if __name__ == '__main__':
    unittest.main()
