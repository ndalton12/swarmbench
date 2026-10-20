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
        self.assertEqual(workflow.run('CSVRéponse_identifier_4_id'), 'Csv Reponse Identifier 4')

    def test_case_002(self):
        self.assertEqual(workflow.run('XMLRéponse_identifier_17_id'), 'Xml Reponse Identifier 17')

    def test_case_003(self):
        self.assertEqual(workflow.run('APIRéponse_identifier_1_id'), 'Api Reponse Identifier 1')

if __name__ == '__main__':
    unittest.main()
