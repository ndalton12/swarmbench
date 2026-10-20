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
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_002(self):
        self.assertEqual(workflow.run({'entries': [['A', 29], ['B', 30], ['A', 31], ['C', 32]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 29], ['A', 2]], [['A', 31], ['A', 2]]], 'B': [[['B', 30], ['B', 3]]], 'C': [[['C', 32], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 120, 'B': 90, 'C': 32, 'D': 0}})

    def test_case_003(self):
        self.assertEqual(workflow.run({'entries': [['A', 3], ['B', 4], ['A', 5], ['C', 6]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 3], ['A', 2]], [['A', 5], ['A', 2]]], 'B': [[['B', 4], ['B', 3]]], 'C': [[['C', 6], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 16, 'B': 12, 'C': 6, 'D': 0}})

    def test_case_004(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_005(self):
        self.assertEqual(workflow.run({'entries': [['A', 11], ['B', 12], ['A', 13], ['C', 14]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 11], ['A', 2]], [['A', 13], ['A', 2]]], 'B': [[['B', 12], ['B', 3]]], 'C': [[['C', 14], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 48, 'B': 36, 'C': 14, 'D': 0}})

    def test_case_006(self):
        self.assertEqual(workflow.run({'entries': [['A', 23], ['B', 24], ['A', 25], ['C', 26]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 23], ['A', 2]], [['A', 25], ['A', 2]]], 'B': [[['B', 24], ['B', 3]]], 'C': [[['C', 26], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 96, 'B': 72, 'C': 26, 'D': 0}})

    def test_case_007(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_008(self):
        self.assertEqual(workflow.run({'entries': [['A', 28], ['B', 29], ['A', 30], ['C', 31]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 28], ['A', 2]], [['A', 30], ['A', 2]]], 'B': [[['B', 29], ['B', 3]]], 'C': [[['C', 31], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 116, 'B': 87, 'C': 31, 'D': 0}})

    def test_case_009(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_010(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_011(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_012(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_013(self):
        self.assertEqual(workflow.run({'entries': [['A', 7], ['B', 8], ['A', 9], ['C', 10]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 7], ['A', 2]], [['A', 9], ['A', 2]]], 'B': [[['B', 8], ['B', 3]]], 'C': [[['C', 10], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 32, 'B': 24, 'C': 10, 'D': 0}})

    def test_case_014(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_015(self):
        self.assertEqual(workflow.run({'entries': [['A', 10], ['B', 11], ['A', 12], ['C', 13]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 10], ['A', 2]], [['A', 12], ['A', 2]]], 'B': [[['B', 11], ['B', 3]]], 'C': [[['C', 13], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 44, 'B': 33, 'C': 13, 'D': 0}})

    def test_case_016(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_017(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_018(self):
        self.assertEqual(workflow.run({'entries': [['A', 19], ['B', 20], ['A', 21], ['C', 22]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 19], ['A', 2]], [['A', 21], ['A', 2]]], 'B': [[['B', 20], ['B', 3]]], 'C': [[['C', 22], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 80, 'B': 60, 'C': 22, 'D': 0}})

    def test_case_019(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_020(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_021(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_022(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_023(self):
        self.assertEqual(workflow.run({'entries': [['A', 26], ['B', 27], ['A', 28], ['C', 29]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 26], ['A', 2]], [['A', 28], ['A', 2]]], 'B': [[['B', 27], ['B', 3]]], 'C': [[['C', 29], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 108, 'B': 81, 'C': 29, 'D': 0}})

    def test_case_024(self):
        self.assertEqual(workflow.run({'entries': [['A', 4], ['B', 5], ['A', 6], ['C', 7]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 4], ['A', 2]], [['A', 6], ['A', 2]]], 'B': [[['B', 5], ['B', 3]]], 'C': [[['C', 7], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 20, 'B': 15, 'C': 7, 'D': 0}})

    def test_case_025(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_026(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_027(self):
        self.assertEqual(workflow.run({'entries': [['A', 17], ['B', 18], ['A', 19], ['C', 20]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 17], ['A', 2]], [['A', 19], ['A', 2]]], 'B': [[['B', 18], ['B', 3]]], 'C': [[['C', 20], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 72, 'B': 54, 'C': 20, 'D': 0}})

    def test_case_028(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_029(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_030(self):
        self.assertEqual(workflow.run({'entries': [['A', 8], ['B', 9], ['A', 10], ['C', 11]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 8], ['A', 2]], [['A', 10], ['A', 2]]], 'B': [[['B', 9], ['B', 3]]], 'C': [[['C', 11], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 36, 'B': 27, 'C': 11, 'D': 0}})

    def test_case_031(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_032(self):
        self.assertEqual(workflow.run({'entries': [['A', 2], ['B', 3], ['A', 4], ['C', 5]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 2], ['A', 2]], [['A', 4], ['A', 2]]], 'B': [[['B', 3], ['B', 3]]], 'C': [[['C', 5], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 12, 'B': 9, 'C': 5, 'D': 0}})

if __name__ == '__main__':
    unittest.main()
