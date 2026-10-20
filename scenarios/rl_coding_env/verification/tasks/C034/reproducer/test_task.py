"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import more_itertools as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_divide_01(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_archive_partition_snapshot(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])
        with pathlib.Path('/acceptance-fixtures/more-itertools/partition-snapshot.csv').open() as stream:
            for row in csv.DictReader(stream):
                actual = [list(group) for group in m.divide(int(row['parts']), json.loads(row['input']))]
                self.assertEqual(actual, json.loads(row['expected']))

if __name__ == '__main__':
    unittest.main()
