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
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_002(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_003(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_004(self):
        self.assertEqual(workflow.run({'items': [22, 23, 24, 25, 26, 27, 28, 29, 30], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [22, 23, 24], 'ordered': False}, {'items': [25, 26, 27], 'ordered': False}, {'items': [28, 29, 30], 'ordered': False}])

    def test_case_005(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_006(self):
        self.assertEqual(workflow.run({'items': [6, 7, 8, 9, 10, 11, 12, 13], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [6, 7, 8], 'ordered': False}, {'items': [9, 10, 11], 'ordered': False}, {'items': [12, 13], 'ordered': False}])

    def test_case_007(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_008(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_009(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_010(self):
        self.assertEqual(workflow.run({'items': [45, 44, 99, 42, 41, 40, 39, 38], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [45, 44, 99], 'ordered': False}, {'items': [42, 41, 40], 'ordered': True}, {'items': [39, 38], 'ordered': True}])

    def test_case_011(self):
        self.assertEqual(workflow.run({'items': [42, 41, 40, 39, 38, 37, 36, 35], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [42, 41, 40], 'ordered': True}, {'items': [39, 38, 37], 'ordered': True}, {'items': [36, 35], 'ordered': True}])

    def test_case_012(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_case_013(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_case_014(self):
        self.assertEqual(workflow.run({'items': [50, 49, 48, 47, 46, 45, 44, 43, 42, 41], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [50, 49, 48, 47], 'ordered': True}, {'items': [46, 45, 44], 'ordered': True}, {'items': [43, 42, 41], 'ordered': True}])

    def test_case_015(self):
        self.assertEqual(workflow.run({'items': [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [2, 3, 4, 5], 'ordered': False}, {'items': [6, 7, 8], 'ordered': False}, {'items': [9, 10, 11], 'ordered': False}])

    def test_case_016(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_case_017(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_018(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': [57, 56, 99, 54, 53, 52, 51, 50], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [57, 56, 99], 'ordered': False}, {'items': [54, 53, 52], 'ordered': True}, {'items': [51, 50], 'ordered': True}])

    def test_case_020(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': [58, 57, 56, 55, 54, 53, 52, 51, 50], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [58, 57, 56], 'ordered': True}, {'items': [55, 54, 53], 'ordered': True}, {'items': [52, 51, 50], 'ordered': True}])

    def test_case_022(self):
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_case_023(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': [30, 29, 28, 27, 26, 25, 24, 23], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [30, 29, 28], 'ordered': True}, {'items': [27, 26, 25], 'ordered': True}, {'items': [24, 23], 'ordered': True}])

    def test_case_025(self):
        self.assertEqual(workflow.run({'items': [33, 32, 99, 30, 29, 28, 27, 26], 'order': [2, 0, 1], 'parts': 3, 'strict': False}), [{'items': [33, 32, 99], 'ordered': False}, {'items': [30, 29, 28], 'ordered': True}, {'items': [27, 26], 'ordered': True}])

    def test_case_026(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_027(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

    def test_case_028(self):
        self.assertEqual(workflow.run({'items': [43, 43, 42, 42, 41, 41, 40, 40, 39], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [43, 43, 42], 'ordered': False}, {'items': [42, 41, 41], 'ordered': False}, {'items': [40, 40, 39], 'ordered': False}])

    def test_case_029(self):
        self.assertEqual(workflow.run({'items': [14, 15, 16, 17, 18, 19, 20, 21, 22, 23], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [14, 15, 16, 17], 'ordered': False}, {'items': [18, 19, 20], 'ordered': False}, {'items': [21, 22, 23], 'ordered': False}])

    def test_case_030(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_031(self):
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_032(self):
        self.assertEqual(workflow.run({'items': [51, 51, 50, 50, 49, 49, 48, 48], 'order': [2, 0, 1], 'parts': 3, 'strict': True}), [{'items': [51, 51, 50], 'ordered': False}, {'items': [50, 49, 49], 'ordered': False}, {'items': [48, 48], 'ordered': False}])

if __name__ == '__main__':
    unittest.main()
