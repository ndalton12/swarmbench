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
    def test_distribute_01(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_regression_chunked_02(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_regression_windowed_03(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_regression_split_at_04(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_regression_split_before_05(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_regression_split_after_06(self):
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_regression_padded_07(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_regression_divide_08(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_regression_always_iterable_09(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

    def test_regression_consecutive_groups_10(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_regression_difference_11(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_regression_replace_12(self):
        self.assertEqual(list(m.replace([1,2,3,1,2,4], lambda a,b:a==1 and b==2, [9], window_size=2)), [9, 3, 9, 4])

    def test_regression_is_sorted_13(self):
        self.assertEqual(m.is_sorted([9,7,7,1], reverse=True), True)

    def test_regression_distinct_combinations_14(self):
        self.assertEqual(list(m.distinct_combinations('ABC', 2)), [('A', 'B'), ('A', 'C'), ('B', 'C')])

if __name__ == '__main__':
    unittest.main()
