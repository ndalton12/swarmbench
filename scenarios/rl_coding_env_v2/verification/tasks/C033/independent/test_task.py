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
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_002(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [29, 29, 29, 29, 28, 28, 28, 28, 27], 'order': [2, 0, 1], 'strict': False}), [{'items': [29, 29, 28], 'ordered': True}, {'items': [29, 28, 28], 'ordered': True}, {'items': [29, 28, 27], 'ordered': True}])

    def test_case_003(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_004(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [6, 7, 8, 9, 10, 11, 12, 13, 14], 'order': [2, 0, 1], 'strict': True}), [{'items': [6, 9, 12], 'ordered': False}, {'items': [7, 10, 13], 'ordered': False}, {'items': [8, 11, 14], 'ordered': False}])

    def test_case_005(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [31, 30, 29, 28, 27, 26, 99, 24, 23], 'order': [2, 0, 1], 'strict': False}), [{'items': [31, 28, 99], 'ordered': False}, {'items': [30, 27, 24], 'ordered': True}, {'items': [29, 26, 23], 'ordered': True}])

    def test_case_006(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_007(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_008(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [27, 26, 25, 24, 23, 22, 99, 20, 19], 'order': [2, 0, 1], 'strict': True}), [{'items': [27, 24, 99], 'ordered': False}, {'items': [26, 23, 20], 'ordered': True}, {'items': [25, 22, 19], 'ordered': True}])

    def test_case_009(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_010(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_011(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_012(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_013(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

    def test_case_014(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [14, 15, 16, 17, 18, 19, 20, 21, 22], 'order': [2, 0, 1], 'strict': True}), [{'items': [14, 17, 20], 'ordered': False}, {'items': [15, 18, 21], 'ordered': False}, {'items': [16, 19, 22], 'ordered': False}])

    def test_case_015(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_016(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_017(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_018(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [24, 23, 22, 21, 20, 19, 18, 17, 16], 'order': [2, 0, 1], 'strict': True}), [{'items': [24, 21, 18], 'ordered': True}, {'items': [23, 20, 17], 'ordered': True}, {'items': [22, 19, 16], 'ordered': True}])

    def test_case_019(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [36, 35, 34, 33, 32, 31, 30, 29, 28], 'order': [2, 0, 1], 'strict': False}), [{'items': [36, 33, 30], 'ordered': True}, {'items': [35, 32, 29], 'ordered': True}, {'items': [34, 31, 28], 'ordered': True}])

    def test_case_020(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_021(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [48, 47, 46, 45, 44, 43, 42, 41, 40], 'order': [2, 0, 1], 'strict': True}), [{'items': [48, 45, 42], 'ordered': True}, {'items': [47, 44, 41], 'ordered': True}, {'items': [46, 43, 40], 'ordered': True}])

    def test_case_022(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_023(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [49, 49, 49, 49, 48, 48, 48, 48, 47], 'order': [2, 0, 1], 'strict': True}), [{'items': [49, 49, 48], 'ordered': False}, {'items': [49, 48, 48], 'ordered': False}, {'items': [49, 48, 47], 'ordered': True}])

    def test_case_024(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [41, 41, 41, 41, 40, 40, 40, 40, 39], 'order': [2, 0, 1], 'strict': True}), [{'items': [41, 41, 40], 'ordered': False}, {'items': [41, 40, 40], 'ordered': False}, {'items': [41, 40, 39], 'ordered': True}])

    def test_case_025(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_026(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [18, 19, 20, 21, 22, 23, 24, 25, 26], 'order': [2, 0, 1], 'strict': False}), [{'items': [18, 21, 24], 'ordered': False}, {'items': [19, 22, 25], 'ordered': False}, {'items': [20, 23, 26], 'ordered': False}])

    def test_case_027(self):
        self.assertEqual(list(m.difference([])), [])

    def test_case_028(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [20, 19, 18, 17, 16, 15, 14, 13, 12], 'order': [2, 0, 1], 'strict': False}), [{'items': [20, 17, 14], 'ordered': True}, {'items': [19, 16, 13], 'ordered': True}, {'items': [18, 15, 12], 'ordered': True}])

    def test_case_029(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [22, 23, 24, 25, 26, 27, 28, 29, 30], 'order': [2, 0, 1], 'strict': True}), [{'items': [22, 25, 28], 'ordered': False}, {'items': [23, 26, 29], 'ordered': False}, {'items': [24, 27, 30], 'ordered': False}])

    def test_case_030(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_031(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_032(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

if __name__ == '__main__':
    unittest.main()
