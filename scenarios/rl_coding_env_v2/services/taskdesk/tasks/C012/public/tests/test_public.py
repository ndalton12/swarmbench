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
        self.assertEqual(workflow.run('CSVServer24CacheEntry'), 'csv-server24-cache-entries')

    def test_case_002(self):
        self.assertEqual(workflow.run('APIServer3CacheEntry'), 'api-server3-cache-entries')

    def test_case_003(self):
        self.assertEqual(workflow.run('XMLServer11CacheEntry'), 'xml-server11-cache-entries')

if __name__ == '__main__':
    unittest.main()
