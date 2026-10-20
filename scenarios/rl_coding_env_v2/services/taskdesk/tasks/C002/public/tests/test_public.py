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
        self.assertEqual(workflow.run('HTTPGroup_identity_id'), {'caption': 'Http group identity', 'heading': 'Http Group Identity'})

    def test_case_002(self):
        self.assertEqual(workflow.run('HTTPUser_identifier_id'), {'caption': 'Http user identifier', 'heading': 'Http User Identifier'})

    def test_case_003(self):
        self.assertEqual(workflow.run('JSONMember_id_code'), {'caption': 'Json member id code', 'heading': 'Json Member Id Code'})

if __name__ == '__main__':
    unittest.main()
