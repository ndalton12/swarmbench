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
        self.assertEqual(workflow.run('élève_identifier_3_id'), {'label': 'Eleve identifier 3', 'slug': 'eleve+identifier+3'})

    def test_case_002(self):
        self.assertEqual(workflow.run('naïve_identifier_14_id'), {'label': 'Naive identifier 14', 'slug': 'naive+identifier+14'})

    def test_case_003(self):
        self.assertEqual(workflow.run('résumé_identifier_12_id'), {'label': 'Resume identifier 12', 'slug': 'resume+identifier+12'})

if __name__ == '__main__':
    unittest.main()
