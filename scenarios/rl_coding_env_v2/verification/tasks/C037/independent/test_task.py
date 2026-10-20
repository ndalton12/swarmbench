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
        self.assertEqual(workflow.run({'items': [27, 81, 189, 405], 'strict': False}), {'changes': [27, 54, 108, 216], 'ordered': False})

    def test_case_002(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': [11, 22, 33, 44], 'strict': False}), {'changes': [11, 11, 11, 11], 'ordered': True})

    def test_case_004(self):
        self.assertEqual(workflow.run({'items': [47, 50, 56, 57], 'strict': False}), {'changes': [47, 3, 6, 1], 'ordered': False})

    def test_case_005(self):
        self.assertEqual(list(m.difference([])), [])

    def test_case_006(self):
        self.assertEqual(workflow.run({'items': [27, 30, 36, 37], 'strict': True}), {'changes': [27, 3, 6, 1], 'ordered': False})

    def test_case_007(self):
        self.assertEqual(workflow.run({'items': [23, 69, 161, 345], 'strict': True}), {'changes': [23, 46, 92, 184], 'ordered': False})

    def test_case_008(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_009(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_010(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_011(self):
        self.assertEqual(workflow.run({'items': [22, 29, 34, 37], 'strict': True}), {'changes': [22, 7, 5, 3], 'ordered': True})

    def test_case_012(self):
        self.assertEqual(workflow.run({'items': [15, 45, 105, 225], 'strict': True}), {'changes': [15, 30, 60, 120], 'ordered': False})

    def test_case_013(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_014(self):
        self.assertEqual(workflow.run({'items': [19, 38, 57, 76], 'strict': False}), {'changes': [19, 19, 19, 19], 'ordered': True})

    def test_case_015(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_016(self):
        self.assertEqual(workflow.run({'items': [3, 9, 21, 45], 'strict': False}), {'changes': [3, 6, 12, 24], 'ordered': False})

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': [27, 54, 81, 108], 'strict': False}), {'changes': [27, 27, 27, 27], 'ordered': True})

    def test_case_018(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': [43, 46, 52, 53], 'strict': True}), {'changes': [43, 3, 6, 1], 'ordered': False})

    def test_case_020(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_021(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_022(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_023(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_024(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_025(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_026(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_027(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_028(self):
        self.assertEqual(workflow.run({'items': [19, 57, 133, 285], 'strict': False}), {'changes': [19, 38, 76, 152], 'ordered': False})

    def test_case_029(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_030(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_031(self):
        self.assertEqual(workflow.run({'items': [30, 37, 42, 45], 'strict': True}), {'changes': [30, 7, 5, 3], 'ordered': True})

    def test_case_032(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

if __name__ == '__main__':
    unittest.main()
