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
        self.assertEqual(workflow.run(['head17', 'escape', ',', 'middle17', ',', 'tail17', ',', 'end']), [['head17', 'literal-comma', 'middle17'], ['tail17', ',', 'end']])

    def test_case_002(self):
        self.assertEqual(workflow.run(['head27', 'escape', ',', 'middle27', ',', 'tail27', ',', 'end']), [['head27', 'literal-comma', 'middle27'], ['tail27', ',', 'end']])

    def test_case_003(self):
        self.assertEqual(workflow.run(['head18', 'escape', ',', 'middle18', ',', 'tail18', ',', 'end']), [['head18', 'literal-comma', 'middle18'], ['tail18', ',', 'end']])

if __name__ == '__main__':
    unittest.main()
