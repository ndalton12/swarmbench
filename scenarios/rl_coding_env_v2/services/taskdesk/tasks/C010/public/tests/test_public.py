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
        self.assertEqual(workflow.run('JSONRéponseRésumé22Item'), 'json+reponse+resume22+item')

    def test_case_002(self):
        self.assertEqual(workflow.run('XMLRéponseRésumé1Item'), 'xml+reponse+resume1+item')

    def test_case_003(self):
        self.assertEqual(workflow.run('CSVRéponseRésumé9Item'), 'csv+reponse+resume9+item')

if __name__ == '__main__':
    unittest.main()
