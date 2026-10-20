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
    def test_tail_01(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_tail_02(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_regression_unique_03(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_regression_accumulate_04(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_regression_interleave_05(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_regression_get_06(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_regression_interpose_07(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_regression_frequencies_08(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_regression_reduceby_09(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_regression_sliding_window_10(self):
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_regression_partition_all_11(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_regression_pluck_12(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_regression_join_13(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_regression_topk_14(self):
        self.assertEqual(m.topk(2, [(1,'a'),(3,'b'),(2,'c')], key=0), ((3, 'b'), (2, 'c')))

    def test_regression_peekn_15(self):
        self.assertEqual((lambda p: (p[0], list(p[1])))(m.peekn(5, iter('ab'))), (('a', 'b'), ['a', 'b']))

if __name__ == '__main__':
    unittest.main()
