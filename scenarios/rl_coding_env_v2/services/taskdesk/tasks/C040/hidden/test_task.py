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
        self.assertEqual(workflow.run({'features': ['A11', 'A11', 'B11', 'C11'], 'size': 3}), [['A11', 'A11', 'B11'], ['A11', 'A11', 'C11'], ['A11', 'B11', 'C11']])

    def test_case_002(self):
        self.assertEqual(workflow.run({'features': 'AB4', 'size': 2}), [])

    def test_case_003(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_004(self):
        self.assertEqual(workflow.run({'features': ['A15', 'A15', 'B15', 'C15'], 'size': 3}), [['A15', 'A15', 'B15'], ['A15', 'A15', 'C15'], ['A15', 'B15', 'C15']])

    def test_case_005(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_006(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_case_007(self):
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_case_008(self):
        self.assertEqual(workflow.run({'features': ['A13', 'A13', 'B13', 'C13'], 'size': 3}), [['A13', 'A13', 'B13'], ['A13', 'A13', 'C13'], ['A13', 'B13', 'C13']])

    def test_case_009(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_010(self):
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_011(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_012(self):
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_013(self):
        self.assertEqual(workflow.run({'features': ['A21', 'A21', 'B21', 'C21'], 'size': 3}), [['A21', 'A21', 'B21'], ['A21', 'A21', 'C21'], ['A21', 'B21', 'C21']])

    def test_case_014(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_015(self):
        self.assertEqual(workflow.run({'features': ['A27', 'A27', 'B27', 'C27'], 'size': 3}), [['A27', 'A27', 'B27'], ['A27', 'A27', 'C27'], ['A27', 'B27', 'C27']])

    def test_case_016(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_017(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_018(self):
        self.assertEqual(workflow.run({'features': 'AB6', 'size': 2}), [])

    def test_case_019(self):
        self.assertEqual(workflow.run({'features': ['A23', 'A23', 'B23', 'C23'], 'size': 3}), [['A23', 'A23', 'B23'], ['A23', 'A23', 'C23'], ['A23', 'B23', 'C23']])

    def test_case_020(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'features': ['A17', 'A17', 'B17', 'C17'], 'size': 3}), [['A17', 'A17', 'B17'], ['A17', 'A17', 'C17'], ['A17', 'B17', 'C17']])

    def test_case_022(self):
        self.assertEqual(workflow.run({'features': 'AB4', 'size': 2}), [])
        self.assertEqual(list(m.distinct_combinations('ABC', 2)), [('A', 'B'), ('A', 'C'), ('B', 'C')])
        self.assertEqual(list(m.distinct_combinations('ABC', 2)), [('A', 'A'), ('A', 'B'), ('A', 'C'), ('B', 'B'), ('B', 'C'), ('C', 'C')])

    def test_case_023(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_case_024(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_025(self):
        self.assertEqual(workflow.run({'features': ['A7', 'A7', 'B7', 'C7'], 'size': 3}), [['A7', 'A7', 'B7'], ['A7', 'A7', 'C7'], ['A7', 'B7', 'C7']])

    def test_case_026(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_027(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_028(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_029(self):
        self.assertEqual(workflow.run({'features': ['A25', 'A25', 'B25', 'C25'], 'size': 3}), [['A25', 'A25', 'B25'], ['A25', 'A25', 'C25'], ['A25', 'B25', 'C25']])

    def test_case_030(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_case_031(self):
        self.assertEqual(workflow.run({'features': ['A9', 'A9', 'B9', 'C9'], 'size': 3}), [['A9', 'A9', 'B9'], ['A9', 'A9', 'C9'], ['A9', 'B9', 'C9']])

    def test_case_032(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

if __name__ == '__main__':
    unittest.main()
