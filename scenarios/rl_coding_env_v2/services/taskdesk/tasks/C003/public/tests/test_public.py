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
        self.assertEqual(workflow.run(-712), {'label': 'position -712th', 'route': 'position.-712th'})

    def test_case_002(self):
        self.assertEqual(workflow.run(-213), {'label': 'position -213th', 'route': 'position.-213th'})

    def test_case_003(self):
        self.assertEqual(workflow.run(-13), {'label': 'position -13th', 'route': 'position.-13th'})

if __name__ == '__main__':
    unittest.main()
