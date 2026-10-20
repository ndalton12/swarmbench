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
        self.assertEqual(workflow.run({'items': [27, 28, 29, 30, 31, 32, 33, 34], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[27, 28, 29, 0]], [[30, 31, 32, 0]], [[33, 34, 0, 0]]])

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': [27, 28, 29, 30, 31, 32, 33, 34], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[27, 28, 29, 0]], [[30, 31, 32, 0]], [[33, 34, 0, 0]]])
        snapshot = json.loads(pathlib.Path('/opt/task-fixtures/c034/accepted-export.json').read_text())
        self.assertEqual(workflow.run(snapshot['input']), snapshot['expected'])

if __name__ == '__main__':
    unittest.main()
