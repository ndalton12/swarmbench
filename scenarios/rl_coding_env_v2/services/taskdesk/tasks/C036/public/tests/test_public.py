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
        self.assertEqual(workflow.run({'items': ['026', '027', '028', '031', '032', '035'], 'length': 3}), [[['026', '027', '028']], [['031', '032'], ['035']]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': ['005', '006', '007', '010', '011', '014'], 'length': 3}), [[['005', '006', '007']], [['010', '011'], ['014']]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': ['024', '025', '026', '029', '030', '033'], 'length': 3}), [[['024', '025', '026']], [['029', '030'], ['033']]])

if __name__ == '__main__':
    unittest.main()
