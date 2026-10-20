"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import inflection as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_singularize_01(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')

    def test_dictionary_snapshot(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')
        snapshot = pathlib.Path('/acceptance-fixtures/inflection/noun-corpus.txt').read_text()
        for row in snapshot.splitlines():
            plural, singular = row.split('\t')
            self.assertEqual(m.singularize(plural), singular)

if __name__ == '__main__':
    unittest.main()
