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
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_002(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[11, 12, 13, 14, 15, 16], [], [111, 112], [211]]}), [13, 14, 15, 16])

    def test_case_004(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_005(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_006(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[20, 21, 22, 23, 24, 25], [], [120, 121], [220]]}), [23, 24, 25])

    def test_case_007(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_008(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_009(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[29, 30, 31, 32, 33, 34], [], [129, 130], [229]]}), [31, 32, 33, 34])

    def test_case_010(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[0, 1, 2, 3, 4, 5], [], [100, 101], [200]]}), [3, 4, 5])

    def test_case_011(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[25, 26, 27, 28, 29, 30], [], [125, 126], [225]]}), [27, 28, 29, 30])

    def test_case_012(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_013(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_014(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_015(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_016(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[10, 11, 12, 13, 14, 15], [], [110, 111], [210]]}), [13, 14, 15])

    def test_case_017(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[2, 3, 4, 5, 6, 7], [], [102, 103], [202]]}), [5, 6, 7])

    def test_case_018(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_019(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[28, 29, 30, 31, 32, 33], [], [128, 129], [228]]}), [31, 32, 33])

    def test_case_020(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_021(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_022(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[8, 9, 10, 11, 12, 13], [], [108, 109], [208]]}), [11, 12, 13])

    def test_case_023(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[23, 24, 25, 26, 27, 28], [], [123, 124], [223]]}), [25, 26, 27, 28])

    def test_case_024(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_025(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_026(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_027(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[4, 5, 6, 7, 8, 9], [], [104, 105], [204]]}), [7, 8, 9])

    def test_case_028(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_029(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[16, 17, 18, 19, 20, 21], [], [116, 117], [216]]}), [19, 20, 21])

    def test_case_030(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_031(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_032(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[6, 7, 8, 9, 10, 11], [], [106, 107], [206]]}), [9, 10, 11])

if __name__ == '__main__':
    unittest.main()
