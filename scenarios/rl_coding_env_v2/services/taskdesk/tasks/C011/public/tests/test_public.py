"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import inflection as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser9_identifier_id']), 'Equipment http user9 identifier ids')

    def test_case_002(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser26_identifier_id']), 'Rice http user26 identifier ids')

    def test_case_003(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser17_identifier_id']), 'Rice http user17 identifier ids')

if __name__ == '__main__':
    unittest.main()
