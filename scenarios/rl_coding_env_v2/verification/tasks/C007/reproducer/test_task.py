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
        self.assertEqual(workflow.run('JSONGroup12Bluejeans'), 'json-group12-bluejean')

    def test_case_010(self):
        self.assertEqual(workflow.run('JSONGroup12Bluejeans'), 'json-group12-bluejean')
        snapshot = json.loads(pathlib.Path('/opt/task-fixtures/c007/accepted-export.json').read_text())
        self.assertEqual(workflow.run(snapshot['input']), snapshot['expected'])

if __name__ == '__main__':
    unittest.main()
