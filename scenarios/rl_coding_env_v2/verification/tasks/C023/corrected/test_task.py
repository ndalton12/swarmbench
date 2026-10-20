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
        self.assertEqual(workflow.run([{'group': 'A', 'value': 30}, {'group': 'B', 'value': 33}, {'group': 'a', 'value': 37}, {'group': 'C'}, {'group': 'b', 'value': 29}]), {'members': {'A': [['A', 30]], 'B': [['B', 33]], 'C': [['C', 0]], 'a': [['a', 37]], 'b': [['b', 29]]}, 'totals': {'A': 30, 'B': 33, 'C': 0, 'a': 37, 'b': 29}})

    def test_case_002(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_003(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_004(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_005(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 7}, {'group': 'B', 'value': 10}, {'group': 'a', 'value': 14}, {'group': 'C'}, {'group': 'b', 'value': 6}]), {'members': {'A': [['A', 7]], 'B': [['B', 10]], 'C': [['C', 0]], 'a': [['a', 14]], 'b': [['b', 6]]}, 'totals': {'A': 7, 'B': 10, 'C': 0, 'a': 14, 'b': 6}})

    def test_case_006(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_007(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_008(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_009(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_010(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 10}, {'group': 'B', 'value': 13}, {'group': 'a', 'value': 17}, {'group': 'C'}, {'group': 'b', 'value': 9}]), {'members': {'A': [['A', 10]], 'B': [['B', 13]], 'C': [['C', 0]], 'a': [['a', 17]], 'b': [['b', 9]]}, 'totals': {'A': 10, 'B': 13, 'C': 0, 'a': 17, 'b': 9}})

    def test_case_011(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_012(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_013(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 28}, {'group': 'B', 'value': 31}, {'group': 'a', 'value': 35}, {'group': 'C'}, {'group': 'b', 'value': 27}]), {'members': {'A': [['A', 28]], 'B': [['B', 31]], 'C': [['C', 0]], 'a': [['a', 35]], 'b': [['b', 27]]}, 'totals': {'A': 28, 'B': 31, 'C': 0, 'a': 35, 'b': 27}})

    def test_case_014(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_015(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 2}, {'group': 'B', 'value': 5}, {'group': 'a', 'value': 9}, {'group': 'C'}, {'group': 'b', 'value': 1}]), {'members': {'A': [['A', 2]], 'B': [['B', 5]], 'C': [['C', 0]], 'a': [['a', 9]], 'b': [['b', 1]]}, 'totals': {'A': 2, 'B': 5, 'C': 0, 'a': 9, 'b': 1}})

    def test_case_016(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 4}, {'group': 'B', 'value': 7}, {'group': 'a', 'value': 11}, {'group': 'C'}, {'group': 'b', 'value': 3}]), {'members': {'A': [['A', 4]], 'B': [['B', 7]], 'C': [['C', 0]], 'a': [['a', 11]], 'b': [['b', 3]]}, 'totals': {'A': 4, 'B': 7, 'C': 0, 'a': 11, 'b': 3}})

    def test_case_017(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 8}, {'group': 'B', 'value': 11}, {'group': 'a', 'value': 15}, {'group': 'C'}, {'group': 'b', 'value': 7}]), {'members': {'A': [['A', 8]], 'B': [['B', 11]], 'C': [['C', 0]], 'a': [['a', 15]], 'b': [['b', 7]]}, 'totals': {'A': 8, 'B': 11, 'C': 0, 'a': 15, 'b': 7}})

    def test_case_018(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 21}, {'group': 'B', 'value': 24}, {'group': 'a', 'value': 28}, {'group': 'C'}, {'group': 'b', 'value': 20}]), {'members': {'A': [['A', 21]], 'B': [['B', 24]], 'C': [['C', 0]], 'a': [['a', 28]], 'b': [['b', 20]]}, 'totals': {'A': 21, 'B': 24, 'C': 0, 'a': 28, 'b': 20}})

    def test_case_019(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 20}, {'group': 'B', 'value': 23}, {'group': 'a', 'value': 27}, {'group': 'C'}, {'group': 'b', 'value': 19}]), {'members': {'A': [['A', 20]], 'B': [['B', 23]], 'C': [['C', 0]], 'a': [['a', 27]], 'b': [['b', 19]]}, 'totals': {'A': 20, 'B': 23, 'C': 0, 'a': 27, 'b': 19}})

    def test_case_020(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 18}, {'group': 'B', 'value': 21}, {'group': 'a', 'value': 25}, {'group': 'C'}, {'group': 'b', 'value': 17}]), {'members': {'A': [['A', 18]], 'B': [['B', 21]], 'C': [['C', 0]], 'a': [['a', 25]], 'b': [['b', 17]]}, 'totals': {'A': 18, 'B': 21, 'C': 0, 'a': 25, 'b': 17}})

    def test_case_021(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_022(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_023(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_024(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_025(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_026(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_027(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 13}, {'group': 'B', 'value': 16}, {'group': 'a', 'value': 20}, {'group': 'C'}, {'group': 'b', 'value': 12}]), {'members': {'A': [['A', 13]], 'B': [['B', 16]], 'C': [['C', 0]], 'a': [['a', 20]], 'b': [['b', 12]]}, 'totals': {'A': 13, 'B': 16, 'C': 0, 'a': 20, 'b': 12}})

    def test_case_028(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 15}, {'group': 'B', 'value': 18}, {'group': 'a', 'value': 22}, {'group': 'C'}, {'group': 'b', 'value': 14}]), {'members': {'A': [['A', 15]], 'B': [['B', 18]], 'C': [['C', 0]], 'a': [['a', 22]], 'b': [['b', 14]]}, 'totals': {'A': 15, 'B': 18, 'C': 0, 'a': 22, 'b': 14}})

    def test_case_029(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_030(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_031(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 16}, {'group': 'B', 'value': 19}, {'group': 'a', 'value': 23}, {'group': 'C'}, {'group': 'b', 'value': 15}]), {'members': {'A': [['A', 16]], 'B': [['B', 19]], 'C': [['C', 0]], 'a': [['a', 23]], 'b': [['b', 15]]}, 'totals': {'A': 16, 'B': 19, 'C': 0, 'a': 23, 'b': 15}})

    def test_case_032(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

if __name__ == '__main__':
    unittest.main()
