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
        self.assertEqual(workflow.run({'index': 3, 'rows': [{'group': 'A', 'value': 10}, {'group': 'B', 'value': 13}, {'group': 'a', 'value': 17}, {'group': 'C'}, {'group': 'b', 'value': 9}]}), [['C', 0]])

    def test_case_002(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_003(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_004(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_005(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_006(self):
        self.assertEqual(workflow.run({'index': 4, 'rows': [{'group': 'A', 'value': 11}, {'group': 'B', 'value': 14}, {'group': 'a', 'value': 18}, {'group': 'C'}, {'group': 'b', 'value': 10}]}), [['b', 10]])

    def test_case_007(self):
        self.assertEqual(workflow.run({'index': 0, 'rows': [{'group': 'A', 'value': 22}, {'group': 'B', 'value': 25}, {'group': 'a', 'value': 29}, {'group': 'C'}, {'group': 'b', 'value': 21}]}), [['A', 22]])

    def test_case_008(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_009(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_010(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_011(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_012(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_013(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_014(self):
        self.assertEqual(workflow.run({'index': 0, 'rows': [{'group': 'A', 'value': 27}, {'group': 'B', 'value': 30}, {'group': 'a', 'value': 34}, {'group': 'C'}, {'group': 'b', 'value': 26}]}), [['A', 27]])

    def test_case_015(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_016(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_017(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_018(self):
        self.assertEqual(workflow.run({'index': 1, 'rows': [{'group': 'A', 'value': 28}, {'group': 'B', 'value': 31}, {'group': 'a', 'value': 35}, {'group': 'C'}, {'group': 'b', 'value': 27}]}), [['B', 31]])

    def test_case_019(self):
        self.assertEqual(workflow.run({'index': 1, 'rows': [{'group': 'A', 'value': 18}, {'group': 'B', 'value': 21}, {'group': 'a', 'value': 25}, {'group': 'C'}, {'group': 'b', 'value': 17}]}), [['B', 21]])

    def test_case_020(self):
        self.assertEqual(workflow.run({'index': 3, 'rows': [{'group': 'A', 'value': 5}, {'group': 'B', 'value': 8}, {'group': 'a', 'value': 12}, {'group': 'C'}, {'group': 'b', 'value': 4}]}), [['C', 0]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'index': 0, 'rows': [{'group': 'A', 'value': 2}, {'group': 'B', 'value': 5}, {'group': 'a', 'value': 9}, {'group': 'C'}, {'group': 'b', 'value': 1}]}), [['A', 2]])

    def test_case_022(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_023(self):
        self.assertEqual(workflow.run({'index': 4, 'rows': [{'group': 'A', 'value': 6}, {'group': 'B', 'value': 9}, {'group': 'a', 'value': 13}, {'group': 'C'}, {'group': 'b', 'value': 5}]}), [['b', 5]])

    def test_case_024(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_025(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_026(self):
        self.assertEqual(workflow.run({'index': 2, 'rows': [{'group': 'A', 'value': 9}, {'group': 'B', 'value': 12}, {'group': 'a', 'value': 16}, {'group': 'C'}, {'group': 'b', 'value': 8}]}), [['a', 16]])

    def test_case_027(self):
        self.assertEqual(workflow.run({'index': 2, 'rows': [{'group': 'A', 'value': 24}, {'group': 'B', 'value': 27}, {'group': 'a', 'value': 31}, {'group': 'C'}, {'group': 'b', 'value': 23}]}), [['a', 31]])

    def test_case_028(self):
        self.assertEqual(workflow.run({'index': 2, 'rows': [{'group': 'A', 'value': 4}, {'group': 'B', 'value': 7}, {'group': 'a', 'value': 11}, {'group': 'C'}, {'group': 'b', 'value': 3}]}), [['a', 11]])

    def test_case_029(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_030(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_031(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_032(self):
        self.assertEqual(workflow.run({'index': 3, 'rows': [{'group': 'A', 'value': 20}, {'group': 'B', 'value': 23}, {'group': 'a', 'value': 27}, {'group': 'C'}, {'group': 'b', 'value': 19}]}), [['C', 0]])

if __name__ == '__main__':
    unittest.main()
