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
        self.assertEqual(workflow.run('Billing23Person'), {'collection': 'billing23People', 'table': 'billing23_people'})

    def test_case_002(self):
        self.assertEqual(workflow.run('Contact19Person'), {'collection': 'contact19People', 'table': 'contact19_people'})

    def test_case_003(self):
        self.assertEqual(workflow.run('Contact24Person'), {'collection': 'contact24People', 'table': 'contact24_people'})

if __name__ == '__main__':
    unittest.main()
