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
        self.assertEqual(workflow.run('HTTPMetric_id_label'), {'key': 'httpMetricIdLabel', 'label': 'Http metric id label'})

    def test_case_002(self):
        self.assertEqual(workflow.run('JSONOrder_identifier_id'), {'key': 'jsonOrderIdentifierId', 'label': 'Json order identifier'})

    def test_case_003(self):
        self.assertEqual(workflow.run('JSONColumn_identifier_id'), {'key': 'jsonColumnIdentifierId', 'label': 'Json column identifier'})

if __name__ == '__main__':
    unittest.main()
