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
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [8, 9, 10, 11, 12, 13, 14, 15, 16], 'preview': 3, 'size': 3}), {'frames': [[8, 9, 10], [11, 12, 13], [14, 15, 16]], 'preview': [8, 9, 10]})

    def test_case_003(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_004(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_005(self):
        self.assertEqual(workflow.run({'items': [25, 26, 27, 28, 29, 30, 31, 32], 'preview': 2, 'size': 4}), {'frames': [[25, 26, 27, 28], [29, 30, 31, 32]], 'preview': [25, 26]})

    def test_case_006(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_007(self):
        self.assertEqual(workflow.run({'items': [22, 23, 24, 25, 26, 27, 28, 29], 'preview': 2, 'size': 3}), {'frames': [[22, 23, 24], [25, 26, 27], [28, 29]], 'preview': [22, 23]})

    def test_case_008(self):
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17], 'preview': 2, 'size': 3}), {'frames': [[10, 11, 12], [13, 14, 15], [16, 17]], 'preview': [10, 11]})
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_009(self):
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17], 'preview': 2, 'size': 3}), {'frames': [[10, 11, 12], [13, 14, 15], [16, 17]], 'preview': [10, 11]})

    def test_case_010(self):
        self.assertEqual(workflow.run({'items': [26, 27, 28, 29, 30, 31, 32, 33, 34], 'preview': 3, 'size': 3}), {'frames': [[26, 27, 28], [29, 30, 31], [32, 33, 34]], 'preview': [26, 27, 28]})

    def test_case_011(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_012(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_013(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_014(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_015(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_016(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': [2, 3, 4, 5, 6, 7, 8, 9, 10], 'preview': 3, 'size': 3}), {'frames': [[2, 3, 4], [5, 6, 7], [8, 9, 10]], 'preview': [2, 3, 4]})

    def test_case_018(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_019(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_020(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': [3, 4, 5, 6, 7, 8, 9], 'preview': 1, 'size': 4}), {'frames': [[3, 4, 5, 6], [7, 8, 9]], 'preview': [3]})

    def test_case_022(self):
        self.assertEqual(workflow.run({'items': [7, 8, 9, 10, 11, 12, 13, 14], 'preview': 2, 'size': 4}), {'frames': [[7, 8, 9, 10], [11, 12, 13, 14]], 'preview': [7, 8]})

    def test_case_023(self):
        self.assertEqual(workflow.run({'items': [28, 29, 30, 31, 32, 33, 34, 35], 'preview': 2, 'size': 3}), {'frames': [[28, 29, 30], [31, 32, 33], [34, 35]], 'preview': [28, 29]})

    def test_case_024(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_025(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_026(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_027(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_028(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_029(self):
        self.assertEqual(workflow.run({'items': [13, 14, 15, 16, 17, 18, 19, 20], 'preview': 2, 'size': 4}), {'frames': [[13, 14, 15, 16], [17, 18, 19, 20]], 'preview': [13, 14]})

    def test_case_030(self):
        self.assertEqual(workflow.run({'items': [29, 30, 31, 32, 33, 34, 35, 36, 37], 'preview': 3, 'size': 4}), {'frames': [[29, 30, 31, 32], [33, 34, 35, 36], [37]], 'preview': [29, 30, 31]})

    def test_case_031(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_032(self):
        self.assertEqual(workflow.run({'items': [21, 22, 23, 24, 25, 26, 27], 'preview': 1, 'size': 4}), {'frames': [[21, 22, 23, 24], [25, 26, 27]], 'preview': [21]})

if __name__ == '__main__':
    unittest.main()
