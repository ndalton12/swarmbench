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

    def test_interpose_02(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_regression_unique_03(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_regression_accumulate_04(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_regression_interleave_05(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_regression_tail_06(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_regression_get_07(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_regression_frequencies_08(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_regression_reduceby_09(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_regression_sliding_window_10(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_regression_partition_all_11(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_regression_pluck_12(self):
        self.assertEqual(list(m.pluck(['a','b'], [{'a':1,'b':2},{'a':3}], default=0)), [(1, 2), (3, 0)])

    def test_regression_join_13(self):
        self.assertEqual(list(m.join(0, [(1,'a'),(2,'b')], 0, [(1,'x')], right_default=None)), [((1, 'a'), (1, 'x')), ((2, 'b'), None)])

    def test_regression_topk_14(self):
        self.assertEqual(m.topk(3, [5,1,7,4,2]), (7, 5, 4))

    def test_regression_peekn_15(self):
        self.assertEqual((lambda p: (p[0], list(p[1])))(m.peekn(2, iter([1,2,3]))), ((1, 2), [1, 2, 3]))

    def test_tokenizer_reference_file(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

if __name__ == '__main__':
    unittest.main()
