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
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_002(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_003(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_004(self):
        self.assertEqual(workflow.run({'items': [49, 48, 99, 46, 45, 44, 43, 42, 41], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [49, 48, 99], 'ordered': False}, {'items': [46, 45, 44], 'ordered': True}, {'items': [43, 42, 41], 'ordered': True}])

    def test_case_005(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_006(self):
        self.assertEqual(workflow.run({'items': [54, 53, 52, 51, 50, 49, 48, 47], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [54, 53, 52], 'ordered': True}, {'items': [51, 50, 49], 'ordered': True}, {'items': [48, 47], 'ordered': True}])

    def test_case_007(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_008(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_009(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_010(self):
        self.assertEqual(workflow.run({'items': [34, 33, 32, 31, 30, 29, 28, 27, 26], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [34, 33, 32], 'ordered': True}, {'items': [31, 30, 29], 'ordered': True}, {'items': [28, 27, 26], 'ordered': True}])

    def test_case_011(self):
        self.assertEqual(workflow.run({'items': [35, 35, 34, 34, 33, 33, 32, 32, 31, 31], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [35, 35, 34, 34], 'ordered': False}, {'items': [33, 33, 32], 'ordered': False}, {'items': [32, 31, 31], 'ordered': False}])

    def test_case_012(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

    def test_case_013(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_014(self):
        self.assertEqual(workflow.run({'items': [26, 27, 28, 29, 30, 31, 32, 33, 34, 35], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [26, 27, 28, 29], 'ordered': False}, {'items': [30, 31, 32], 'ordered': False}, {'items': [33, 34, 35], 'ordered': False}])

    def test_case_015(self):
        self.assertEqual(workflow.run({'items': [47, 47, 46, 46, 45, 45, 44, 44, 43, 43], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [47, 47, 46, 46], 'ordered': True}, {'items': [45, 45, 44], 'ordered': True}, {'items': [44, 43, 43], 'ordered': True}])

    def test_case_016(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_017(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_018(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': [39, 39, 38, 38, 37, 37, 36, 36], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [39, 39, 38], 'ordered': True}, {'items': [38, 37, 37], 'ordered': True}, {'items': [36, 36], 'ordered': True}])

    def test_case_020(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17, 18], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [10, 11, 12], 'ordered': False}, {'items': [13, 14, 15], 'ordered': False}, {'items': [16, 17, 18], 'ordered': False}])

    def test_case_022(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_023(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': [59, 59, 58, 58, 57, 57, 56, 56, 55, 55], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [59, 59, 58, 58], 'ordered': False}, {'items': [57, 57, 56], 'ordered': False}, {'items': [56, 55, 55], 'ordered': False}])

    def test_case_025(self):
        self.assertEqual(workflow.run({'items': [31, 31, 30, 30, 29, 29, 28, 28, 27], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [31, 31, 30], 'ordered': True}, {'items': [30, 29, 29], 'ordered': True}, {'items': [28, 28, 27], 'ordered': True}])

    def test_case_026(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_027(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_028(self):
        self.assertEqual(workflow.run({'items': [38, 37, 36, 35, 34, 33, 32, 31, 30, 29], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [38, 37, 36, 35], 'ordered': True}, {'items': [34, 33, 32], 'ordered': True}, {'items': [31, 30, 29], 'ordered': True}])

    def test_case_029(self):
        self.assertEqual(workflow.run({'items': [53, 52, 99, 50, 49, 48, 47, 46, 45, 44], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [53, 52, 99, 50], 'ordered': False}, {'items': [49, 48, 47], 'ordered': True}, {'items': [46, 45, 44], 'ordered': True}])

    def test_case_030(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_031(self):
        self.assertEqual(list(m.difference([])), [])

    def test_case_032(self):
        self.assertEqual(workflow.run({'items': [46, 45, 44, 43, 42, 41, 40, 39, 38], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [46, 45, 44], 'ordered': True}, {'items': [43, 42, 41], 'ordered': True}, {'items': [40, 39, 38], 'ordered': True}])

if __name__ == '__main__':
    unittest.main()
