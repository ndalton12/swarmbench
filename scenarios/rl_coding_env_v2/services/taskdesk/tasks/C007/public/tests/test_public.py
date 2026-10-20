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
        self.assertEqual(workflow.run('APIGroup13Bluejeans'), 'api-group13-bluejean')

    def test_case_002(self):
        self.assertEqual(workflow.run('JSONGroup7Bluejeans'), 'json-group7-bluejean')

    def test_case_003(self):
        self.assertEqual(workflow.run('APIGroup18Bluejeans'), 'api-group18-bluejean')

if __name__ == '__main__':
    unittest.main()
