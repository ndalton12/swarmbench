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
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_002(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [28, 27, 26, 25, 24, 23, 22, 21, 20], 'order': [2, 0, 1], 'strict': False}), [{'items': [28, 25, 22], 'ordered': True}, {'items': [27, 24, 21], 'ordered': True}, {'items': [26, 23, 20], 'ordered': True}])

    def test_case_003(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_004(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [23, 22, 21, 20, 19, 18, 99, 16, 15], 'order': [2, 0, 1], 'strict': False}), [{'items': [23, 20, 99], 'ordered': False}, {'items': [22, 19, 16], 'ordered': True}, {'items': [21, 18, 15], 'ordered': True}])

    def test_case_005(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [21, 21, 21, 21, 20, 20, 20, 20, 19], 'order': [2, 0, 1], 'strict': False}), [{'items': [21, 21, 20], 'ordered': True}, {'items': [21, 20, 20], 'ordered': True}, {'items': [21, 20, 19], 'ordered': True}])

    def test_case_006(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_case_007(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_008(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [33, 33, 33, 33, 32, 32, 32, 32, 31], 'order': [2, 0, 1], 'strict': True}), [{'items': [33, 33, 32], 'ordered': False}, {'items': [33, 32, 32], 'ordered': False}, {'items': [33, 32, 31], 'ordered': True}])

    def test_case_009(self):
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_010(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_011(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_012(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_013(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_case_014(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [25, 25, 25, 25, 24, 24, 24, 24, 23], 'order': [2, 0, 1], 'strict': True}), [{'items': [25, 25, 24], 'ordered': False}, {'items': [25, 24, 24], 'ordered': False}, {'items': [25, 24, 23], 'ordered': True}])

    def test_case_015(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_016(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_017(self):
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_case_018(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [32, 31, 30, 29, 28, 27, 26, 25, 24], 'order': [2, 0, 1], 'strict': True}), [{'items': [32, 29, 26], 'ordered': True}, {'items': [31, 28, 25], 'ordered': True}, {'items': [30, 27, 24], 'ordered': True}])

    def test_case_019(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [44, 43, 42, 41, 40, 39, 38, 37, 36], 'order': [2, 0, 1], 'strict': False}), [{'items': [44, 41, 38], 'ordered': True}, {'items': [43, 40, 37], 'ordered': True}, {'items': [42, 39, 36], 'ordered': True}])

    def test_case_020(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_021(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [10, 11, 12, 13, 14, 15, 16, 17, 18], 'order': [2, 0, 1], 'strict': False}), [{'items': [10, 13, 16], 'ordered': False}, {'items': [11, 14, 17], 'ordered': False}, {'items': [12, 15, 18], 'ordered': False}])

    def test_case_022(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_case_023(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [40, 39, 38, 37, 36, 35, 34, 33, 32], 'order': [2, 0, 1], 'strict': True}), [{'items': [40, 37, 34], 'ordered': True}, {'items': [39, 36, 33], 'ordered': True}, {'items': [38, 35, 32], 'ordered': True}])

    def test_case_024(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [26, 27, 28, 29, 30, 31, 32, 33, 34], 'order': [2, 0, 1], 'strict': False}), [{'items': [26, 29, 32], 'ordered': False}, {'items': [27, 30, 33], 'ordered': False}, {'items': [28, 31, 34], 'ordered': False}])

    def test_case_025(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_026(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [39, 38, 37, 36, 35, 34, 99, 32, 31], 'order': [2, 0, 1], 'strict': False}), [{'items': [39, 36, 99], 'ordered': False}, {'items': [38, 35, 32], 'ordered': True}, {'items': [37, 34, 31], 'ordered': True}])

    def test_case_027(self):
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_028(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [35, 34, 33, 32, 31, 30, 99, 28, 27], 'order': [2, 0, 1], 'strict': True}), [{'items': [35, 32, 99], 'ordered': False}, {'items': [34, 31, 28], 'ordered': True}, {'items': [33, 30, 27], 'ordered': True}])

    def test_case_029(self):
        self.assertEqual(workflow.run({'channels': 3, 'items': [47, 46, 45, 44, 43, 42, 99, 40, 39], 'order': [2, 0, 1], 'strict': False}), [{'items': [47, 44, 99], 'ordered': False}, {'items': [46, 43, 40], 'ordered': True}, {'items': [45, 42, 39], 'ordered': True}])

    def test_case_030(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_031(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_032(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

if __name__ == '__main__':
    unittest.main()
