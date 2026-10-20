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
        self.assertEqual(list(m.difference([])), [])

    def test_case_002(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_003(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], 'order': [1, 0], 'size': 3})

    def test_case_004(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_005(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_006(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33], 'order': [1, 0], 'size': 3}), [[[22, 24, 26], [28, 30, 32]], [[23, 25, 27], [29, 31, 33]]])

    def test_case_007(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_008(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_009(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_010(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21], 'order': [0, 1], 'size': 3})

    def test_case_011(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19], 'order': [1, 0], 'size': 3}), [[[8, 10, 12], [14, 16, 18]], [[9, 11, 13], [15, 17, 19]]])

    def test_case_012(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41], 'order': [1, 0], 'size': 3})

    def test_case_013(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_014(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21], 'order': [1, 0], 'size': 3}), [[[10, 12, 14], [16, 18, 20]], [[11, 13, 15], [17, 19, 21]]])

    def test_case_015(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_016(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37], 'order': [1, 0], 'size': 3})

    def test_case_017(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_018(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33], 'order': [0, 1], 'size': 3})

    def test_case_019(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_020(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_021(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17], 'order': [0, 1], 'size': 3}), [[[6, 8, 10], [12, 14, 16]], [[7, 9, 11], [13, 15, 17]]])

    def test_case_022(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_023(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_024(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_025(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_026(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_027(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35], 'order': [0, 1], 'size': 3}), [[[24, 26, 28], [30, 32, 34]], [[25, 27, 29], [31, 33, 35]]])

    def test_case_028(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_029(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], 'order': [1, 0], 'size': 3})

    def test_case_030(self):
        with self.assertRaises(ValueError):
            workflow.run({'channels': 2, 'items': [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], 'order': [0, 1], 'size': 3})

    def test_case_031(self):
        self.assertEqual(workflow.run({'channels': 2, 'items': [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], 'order': [1, 0], 'size': 3}), [[[2, 4, 6], [8, 10, 12]], [[3, 5, 7], [9, 11, 13]]])

    def test_case_032(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

if __name__ == '__main__':
    unittest.main()
