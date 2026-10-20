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
        self.assertEqual(workflow.run({'items': ['008', '009', '011', '012', '015', '016'], 'threshold': 11}), [[['008', '009']], [['011', '012'], ['015', '016']]])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': ['004', '005', '007', '008', '011', '012'], 'threshold': 7}), [[['004', '005']], [['007', '008'], ['011', '012']]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': ['016', '017', '019', '020', '023', '024'], 'threshold': 19}), [[['016', '017']], [['019', '020'], ['023', '024']]])

if __name__ == '__main__':
    unittest.main()
