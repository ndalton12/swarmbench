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
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPGroup10Person']), 'informationHttpGroup10People')

    def test_case_002(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPGroup27Person']), 'equipmentHttpGroup27People')

    def test_case_003(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPGroup23Person']), 'riceHttpGroup23People')

if __name__ == '__main__':
    unittest.main()
