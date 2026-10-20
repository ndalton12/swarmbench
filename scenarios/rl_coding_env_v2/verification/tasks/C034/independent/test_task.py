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
        self.assertEqual(workflow.run({'items': [8, 9, 10, 11, 12, 13, 14, 15, 16, 17], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[8, 9, 10]], [[12, 13, 14]], [[15, 16, 17]]])

    def test_case_002(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_003(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_004(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_005(self):
        self.assertEqual(workflow.run({'items': [4, 5, 6, 7, 8, 9, 10, 11, 12], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[4, 5, 6]], [[7, 8, 9]], [[10, 11, 12]]])

    def test_case_006(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_007(self):
        self.assertEqual(list(m.difference([])), [])

    def test_case_008(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_009(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_010(self):
        self.assertEqual(workflow.run({'items': [3, 4, 5, 6, 7, 8, 9, 10], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[3, 4, 5, 0]], [[6, 7, 8, 0]], [[9, 10, 0, 0]]])

    def test_case_011(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

    def test_case_012(self):
        self.assertEqual(workflow.run({'items': [14, 15, 16, 17, 18, 19, 20, 21, 22, 23], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[14, 15, 16]], [[18, 19, 20]], [[21, 22, 23]]])

    def test_case_013(self):
        self.assertEqual(workflow.run({'items': [12, 13, 14, 15, 16, 17, 18, 19], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[12, 13, 14]], [[15, 16, 17]], [[18, 19, 0]]])

    def test_case_014(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_015(self):
        self.assertEqual(workflow.run({'items': [24, 25, 26, 27, 28, 29, 30, 31], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[24, 25, 26]], [[27, 28, 29]], [[30, 31, 0]]])

    def test_case_016(self):
        self.assertEqual(workflow.run({'items': [5, 6, 7, 8, 9, 10, 11, 12, 13, 14], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[5, 6, 7, 8]], [[9, 10, 11, 0]], [[12, 13, 14, 0]]])

    def test_case_017(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_018(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_019(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': [20, 21, 22, 23, 24, 25, 26, 27, 28, 29], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[20, 21, 22]], [[24, 25, 26]], [[27, 28, 29]]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': [7, 8, 9, 10, 11, 12, 13, 14, 15], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[7, 8, 9, 0]], [[10, 11, 12, 0]], [[13, 14, 15, 0]]])

    def test_case_022(self):
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17, 18], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[10, 11, 12]], [[13, 14, 15]], [[16, 17, 18]]])

    def test_case_023(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': [21, 22, 23, 24, 25, 26, 27, 28], 'order': [2, 0, 1], 'parts': 3, 'step': 5, 'width': 4}), [[[21, 22, 23, 0]], [[24, 25, 26, 0]], [[27, 28, 0, 0]]])

    def test_case_025(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_026(self):
        self.assertEqual(workflow.run({'items': [0, 1, 2, 3, 4, 5, 6, 7], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[0, 1, 2]], [[3, 4, 5]], [[6, 7, 0]]])

    def test_case_027(self):
        self.assertEqual(workflow.run({'items': [28, 29, 30, 31, 32, 33, 34, 35, 36], 'order': [2, 0, 1], 'parts': 3, 'step': 4, 'width': 3}), [[[28, 29, 30]], [[31, 32, 33]], [[34, 35, 36]]])

    def test_case_028(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_029(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_030(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_031(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_032(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

if __name__ == '__main__':
    unittest.main()
