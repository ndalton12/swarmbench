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
        self.assertEqual(workflow.run({'items': [13, 14, 15, 16, 17, 18, 19, 20], 'size': 4}), [[13, 14, 15, 16], ['boundary'], [17, 18, 19, 20]])

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': [13, 14, 15, 16, 17, 18, 19, 20], 'size': 4}), [[13, 14, 15, 16], ['boundary'], [17, 18, 19, 20]])
        snapshot = json.loads(pathlib.Path('/opt/task-fixtures/c018/accepted-export.json').read_text())
        self.assertEqual(workflow.run(snapshot['input']), snapshot['expected'])

if __name__ == '__main__':
    unittest.main()
