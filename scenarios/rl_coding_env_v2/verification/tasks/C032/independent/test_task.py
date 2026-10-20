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
        self.assertEqual(workflow.run({'items': [7, 8, 9, 10, 11, 12, 13], 'minimum': 3, 'order': [2, 0, 1], 'parts': 3}), [[7, 8, 9], [10, 11], [12, 13]])

    def test_case_002(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_003(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_004(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_005(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_006(self):
        self.assertEqual(workflow.run({'items': [6, 7, 8, 9, 10, 11, 12], 'minimum': 9, 'order': [1, 2, 0], 'parts': 3}), [[6, 7, 8], [9, 10, 11], [12, 0, 0]])

    def test_case_007(self):
        self.assertEqual(workflow.run({'items': [16, 17, 18, 19, 20, 21, 22], 'minimum': 5, 'order': [1, 2, 0], 'parts': 3}), [[16, 17, 18], [19, 20], [21, 22]])

    def test_case_008(self):
        self.assertEqual(workflow.run({'items': [13, 14, 15, 16, 17, 18, 19], 'minimum': 9, 'order': [2, 0, 1], 'parts': 3}), [[13, 14, 15], [16, 17, 18], [19, 0, 0]])

    def test_case_009(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_010(self):
        self.assertEqual(workflow.run({'items': [18, 19, 20, 21, 22, 23, 24], 'minimum': 7, 'order': [1, 2, 0], 'parts': 3}), [[18, 19, 20], [21, 22], [23, 24]])

    def test_case_011(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_012(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_013(self):
        self.assertEqual(workflow.run({'items': [19, 20, 21, 22, 23, 24, 25], 'minimum': 8, 'order': [2, 0, 1], 'parts': 3}), [[19, 20, 21], [22, 23, 24], [25, 0]])

    def test_case_014(self):
        self.assertEqual(workflow.run({'items': [27, 28, 29, 30, 31, 32, 33], 'minimum': 9, 'order': [2, 0, 1], 'parts': 3}), [[27, 28, 29], [30, 31, 32], [33, 0, 0]])

    def test_case_015(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

    def test_case_016(self):
        self.assertEqual(workflow.run({'items': [21, 22, 23, 24, 25, 26, 27], 'minimum': 3, 'order': [2, 0, 1], 'parts': 3}), [[21, 22, 23], [24, 25], [26, 27]])

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': [24, 25, 26, 27, 28, 29, 30], 'minimum': 6, 'order': [1, 2, 0], 'parts': 3}), [[24, 25, 26], [27, 28], [29, 30]])

    def test_case_018(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': [2, 3, 4, 5, 6, 7, 8], 'minimum': 5, 'order': [1, 2, 0], 'parts': 3}), [[2, 3, 4], [5, 6], [7, 8]])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': [20, 21, 22, 23, 24, 25, 26], 'minimum': 9, 'order': [1, 2, 0], 'parts': 3}), [[20, 21, 22], [23, 24, 25], [26, 0, 0]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': [22, 23, 24, 25, 26, 27, 28], 'minimum': 4, 'order': [1, 2, 0], 'parts': 3}), [[22, 23, 24], [25, 26], [27, 28]])

    def test_case_022(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_023(self):
        self.assertEqual(list(m.difference([])), [])

    def test_case_024(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_025(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_026(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_027(self):
        self.assertEqual(workflow.run({'items': [29, 30, 31, 32, 33, 34, 35], 'minimum': 4, 'order': [2, 0, 1], 'parts': 3}), [[29, 30, 31], [32, 33], [34, 35]])

    def test_case_028(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_029(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_030(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_031(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_032(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

if __name__ == '__main__':
    unittest.main()
