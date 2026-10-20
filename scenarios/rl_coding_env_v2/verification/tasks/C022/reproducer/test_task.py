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
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17], 'preview': 2, 'size': 3}), {'frames': [[10, 11, 12], [13, 14, 15], [16, 17]], 'preview': [10, 11]})

    def test_case_008(self):
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17], 'preview': 2, 'size': 3}), {'frames': [[10, 11, 12], [13, 14, 15], [16, 17]], 'preview': [10, 11]})
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5, None)])

if __name__ == '__main__':
    unittest.main()
