"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import toolz as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_002(self):
        self.assertEqual(workflow.run({'opening': 125, 'readings': [35, 41, 38, 45, 44]}), [125, 119, 122, 115, 116])

    def test_case_003(self):
        self.assertEqual(workflow.run({'opening': 113, 'readings': [23, 29, 26, 33, 32]}), [113, 107, 110, 103, 104])

    def test_case_004(self):
        self.assertEqual(workflow.run({'opening': 102, 'readings': [12, 18, 15, 22, 21]}), [102, 96, 99, 92, 93])

    def test_case_005(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_006(self):
        self.assertEqual(workflow.run({'opening': 112, 'readings': [22, 28, 25, 32, 31]}), [112, 106, 109, 102, 103])

    def test_case_007(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_008(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_009(self):
        self.assertEqual(workflow.run({'opening': 118, 'readings': [28, 34, 31, 38, 37]}), [118, 112, 115, 108, 109])

    def test_case_010(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_011(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_012(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_013(self):
        self.assertEqual(workflow.run({'opening': 123, 'readings': [33, 39, 36, 43, 42]}), [123, 117, 120, 113, 114])

    def test_case_014(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_015(self):
        self.assertEqual(workflow.run({'opening': 120, 'readings': [30, 36, 33, 40, 39]}), [120, 114, 117, 110, 111])

    def test_case_016(self):
        self.assertEqual(workflow.run({'opening': 105, 'readings': [15, 21, 18, 25, 24]}), [105, 99, 102, 95, 96])

    def test_case_017(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_018(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_019(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_020(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_021(self):
        self.assertEqual(workflow.run({'opening': 119, 'readings': [29, 35, 32, 39, 38]}), [119, 113, 116, 109, 110])

    def test_case_022(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_023(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_024(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_025(self):
        self.assertEqual(workflow.run({'opening': 112, 'readings': [22, 28, 25, 32, 31]}), [112, 106, 109, 102, 103])

    def test_case_026(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_027(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_028(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_029(self):
        self.assertEqual(workflow.run({'opening': 109, 'readings': [19, 25, 22, 29, 28]}), [109, 103, 106, 99, 100])

    def test_case_030(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_031(self):
        self.assertEqual(workflow.run({'opening': 129, 'readings': [39, 45, 42, 49, 48]}), [129, 123, 126, 119, 120])

    def test_case_032(self):
        self.assertEqual(workflow.run({'opening': 116, 'readings': [26, 32, 29, 36, 35]}), [116, 110, 113, 106, 107])

if __name__ == '__main__':
    unittest.main()
