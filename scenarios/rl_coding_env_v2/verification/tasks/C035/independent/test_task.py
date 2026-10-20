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
        self.assertEqual(workflow.run({'fields': ['secret29', 'visible', 'secret29', 'tail'], 'limit': 2, 'target': 'secret29'}), ['redacted', 'visible', 'redacted', 'tail'])

    def test_case_002(self):
        self.assertEqual(workflow.run({'fields': ['secret7', 'visible', 'secret7', 'tail'], 'limit': 1, 'target': 'secret7'}), ['redacted', 'visible', 'secret7', 'tail'])

    def test_case_003(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_004(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_005(self):
        self.assertEqual(workflow.run({'fields': ['secret26', 'visible', 'secret26', 'tail'], 'limit': 2, 'target': 'secret26'}), ['redacted', 'visible', 'redacted', 'tail'])

    def test_case_006(self):
        self.assertEqual(workflow.run({'fields': 'secret27', 'limit': 0, 'target': 'secret27'}), ['secret27'])

    def test_case_007(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_008(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_009(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_010(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_011(self):
        self.assertEqual(workflow.run({'fields': ['secret11', 'visible', 'secret11', 'tail'], 'limit': 2, 'target': 'secret11'}), ['redacted', 'visible', 'redacted', 'tail'])

    def test_case_012(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_013(self):
        self.assertEqual(workflow.run({'fields': ['secret16', 'visible', 'secret16', 'tail'], 'limit': 1, 'target': 'secret16'}), ['redacted', 'visible', 'secret16', 'tail'])

    def test_case_014(self):
        self.assertEqual(list(m.difference([])), [])

    def test_case_015(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_016(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

    def test_case_017(self):
        self.assertEqual(workflow.run({'fields': ['secret4', 'visible', 'secret4', 'tail'], 'limit': 1, 'target': 'secret4'}), ['redacted', 'visible', 'secret4', 'tail'])

    def test_case_018(self):
        self.assertEqual(workflow.run({'fields': 'secret12', 'limit': 0, 'target': 'secret12'}), ['secret12'])

    def test_case_019(self):
        self.assertEqual(workflow.run({'fields': ['secret2', 'visible', 'secret2', 'tail'], 'limit': 2, 'target': 'secret2'}), ['redacted', 'visible', 'redacted', 'tail'])

    def test_case_020(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'fields': ['secret22', 'visible', 'secret22', 'tail'], 'limit': 1, 'target': 'secret22'}), ['redacted', 'visible', 'secret22', 'tail'])

    def test_case_022(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_023(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_024(self):
        self.assertEqual(workflow.run({'fields': ['secret10', 'visible', 'secret10', 'tail'], 'limit': 1, 'target': 'secret10'}), ['redacted', 'visible', 'secret10', 'tail'])

    def test_case_025(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_026(self):
        self.assertEqual(workflow.run({'fields': ['secret19', 'visible', 'secret19', 'tail'], 'limit': 1, 'target': 'secret19'}), ['redacted', 'visible', 'secret19', 'tail'])

    def test_case_027(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_028(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_029(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_030(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_031(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_032(self):
        self.assertEqual(workflow.run({'fields': ['secret20', 'visible', 'secret20', 'tail'], 'limit': 2, 'target': 'secret20'}), ['redacted', 'visible', 'redacted', 'tail'])

if __name__ == '__main__':
    unittest.main()
