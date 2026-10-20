"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import toolz as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_interpose_01(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_tokenizer_reference_file(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])
        snapshot = json.loads(pathlib.Path('/acceptance-fixtures/toolz/token-separators.json').read_text())
        for row in snapshot:
            self.assertEqual(list(m.interpose(row['separator'], row['input'])), row['expected'])

if __name__ == '__main__':
    unittest.main()
