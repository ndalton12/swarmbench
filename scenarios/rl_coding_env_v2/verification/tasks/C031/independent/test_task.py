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
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_003(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_004(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_005(self):
        self.assertEqual(workflow.run({'items': ['entry6', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry6', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_006(self):
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry27', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

    def test_case_007(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_008(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_009(self):
        self.assertEqual(workflow.run({'items': ['entry22', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry22', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_010(self):
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry3', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

    def test_case_011(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_012(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_013(self):
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry17', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

    def test_case_014(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_015(self):
        self.assertEqual(workflow.run({'items': ['entry4', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry4', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_016(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_017(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_018(self):
        self.assertEqual(workflow.run({'items': ['entry8', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry8', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_019(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': ['entry28', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry28', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': ['entry16', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry16', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_022(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_023(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_024(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_025(self):
        self.assertEqual(workflow.run({'items': ['entry0', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry0', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_026(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_027(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_028(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_029(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

    def test_case_030(self):
        self.assertEqual(workflow.run({'items': ['entry24', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry24', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_031(self):
        self.assertEqual(workflow.run({'items': ['entry10', 'commit', '0', '1', '2', '3'], 'size': 2}), [[['entry10', 'commit']], [['0', '1'], ['2', '3']]])

    def test_case_032(self):
        with self.assertRaises(ValueError):
            workflow.run({'items': ['entry21', 'commit', '0', '1', '2', '3', '4'], 'size': 2})

if __name__ == '__main__':
    unittest.main()
