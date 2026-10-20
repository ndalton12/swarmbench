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
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': [24, 25, 26, 27, 28, 29, 30], 'size': 3}), [[24, 25, 26], ['boundary'], [27, 28, 29], ['boundary'], [30]])

    def test_case_003(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_004(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_005(self):
        self.assertEqual(workflow.run({'items': [16, 17, 18, 19, 20, 21, 22, 23], 'size': 3}), [[16, 17, 18], ['boundary'], [19, 20, 21], ['boundary'], [22, 23]])

    def test_case_006(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_007(self):
        self.assertEqual(workflow.run({'items': [10, 11, 12, 13, 14, 15, 16, 17], 'size': 3}), [[10, 11, 12], ['boundary'], [13, 14, 15], ['boundary'], [16, 17]])

    def test_case_008(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_009(self):
        self.assertEqual(workflow.run({'items': [9, 10, 11, 12, 13, 14, 15], 'size': 4}), [[9, 10, 11, 12], ['boundary'], [13, 14, 15]])

    def test_case_010(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_011(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_012(self):
        self.assertEqual(workflow.run({'items': [18, 19, 20, 21, 22, 23, 24], 'size': 3}), [[18, 19, 20], ['boundary'], [21, 22, 23], ['boundary'], [24]])

    def test_case_013(self):
        self.assertEqual(workflow.run({'items': [19, 20, 21, 22, 23, 24, 25, 26], 'size': 4}), [[19, 20, 21, 22], ['boundary'], [23, 24, 25, 26]])

    def test_case_014(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_015(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_016(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': [13, 14, 15, 16, 17, 18, 19, 20], 'size': 4}), [[13, 14, 15, 16], ['boundary'], [17, 18, 19, 20]])
        snapshot = json.loads(pathlib.Path('/opt/task-fixtures/c018/accepted-export.json').read_text())
        self.assertEqual(workflow.run(snapshot['input']), snapshot['expected'])

    def test_case_018(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': [27, 28, 29, 30, 31, 32, 33], 'size': 4}), [[27, 28, 29, 30], ['boundary'], [31, 32, 33]])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': [26, 27, 28, 29, 30, 31, 32, 33, 34], 'size': 3}), [[26, 27, 28], ['boundary'], [29, 30, 31], ['boundary'], [32, 33, 34]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': [21, 22, 23, 24, 25, 26, 27], 'size': 4}), [[21, 22, 23, 24], ['boundary'], [25, 26, 27]])

    def test_case_022(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_023(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': [13, 14, 15, 16, 17, 18, 19, 20], 'size': 4}), [[13, 14, 15, 16], ['boundary'], [17, 18, 19, 20]])

    def test_case_025(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_026(self):
        self.assertEqual(workflow.run({'items': [23, 24, 25, 26, 27, 28, 29, 30, 31], 'size': 4}), [[23, 24, 25, 26], ['boundary'], [27, 28, 29, 30], ['boundary'], [31]])

    def test_case_027(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_028(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_029(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_030(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_031(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_032(self):
        self.assertEqual(workflow.run({'items': [8, 9, 10, 11, 12, 13, 14, 15, 16], 'size': 3}), [[8, 9, 10], ['boundary'], [11, 12, 13], ['boundary'], [14, 15, 16]])

if __name__ == '__main__':
    unittest.main()
