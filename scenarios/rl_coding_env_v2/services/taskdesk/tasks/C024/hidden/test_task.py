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
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_002(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_003(self):
        self.assertEqual(workflow.run({'entries': [['A', 25], ['B', 26], ['A', 33], ['C', 27], ['B', 32]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 25], ['A', 'x']], [['B', 26], ['B', 'y']], [['A', 25], ['A', 'z']], [['C', 27], None]])

    def test_case_004(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_005(self):
        self.assertEqual(workflow.run({'entries': [['A', 26], ['B', 27], ['A', 34], ['C', 28], ['B', 33]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 26], ['A', 'x']], [['B', 27], ['B', 'y']], [['A', 26], ['A', 'z']], [['C', 28], None]])

    def test_case_006(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_007(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_008(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_009(self):
        self.assertEqual(workflow.run({'entries': [['A', 4], ['B', 5], ['A', 12], ['C', 6], ['B', 11]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 4], ['A', 'x']], [['B', 5], ['B', 'y']], [['A', 4], ['A', 'z']], [['C', 6], None]])

    def test_case_010(self):
        self.assertEqual(workflow.run({'entries': [['A', 27], ['B', 28], ['A', 35], ['C', 29], ['B', 34]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 27], ['A', 'x']], [['B', 28], ['B', 'y']], [['A', 27], ['A', 'z']], [['C', 29], None]])

    def test_case_011(self):
        self.assertEqual(workflow.run({'entries': [['A', 8], ['B', 9], ['A', 16], ['C', 10], ['B', 15]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 8], ['A', 'x']], [['B', 9], ['B', 'y']], [['A', 8], ['A', 'z']], [['C', 10], None]])

    def test_case_012(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_013(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_014(self):
        self.assertEqual(workflow.run({'entries': [['A', 21], ['B', 22], ['A', 29], ['C', 23], ['B', 28]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 21], ['A', 'x']], [['B', 22], ['B', 'y']], [['A', 21], ['A', 'z']], [['C', 23], None]])

    def test_case_015(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_016(self):
        self.assertEqual(workflow.run({'entries': [['A', 19], ['B', 20], ['A', 27], ['C', 21], ['B', 26]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 19], ['A', 'x']], [['B', 20], ['B', 'y']], [['A', 19], ['A', 'z']], [['C', 21], None]])

    def test_case_017(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_018(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_019(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_020(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_021(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_022(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_023(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_024(self):
        self.assertEqual(workflow.run({'entries': [['A', 24], ['B', 25], ['A', 32], ['C', 26], ['B', 31]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 24], ['A', 'x']], [['B', 25], ['B', 'y']], [['A', 24], ['A', 'z']], [['C', 26], None]])

    def test_case_025(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_026(self):
        self.assertEqual(workflow.run({'entries': [['A', 18], ['B', 19], ['A', 26], ['C', 20], ['B', 25]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 18], ['A', 'x']], [['B', 19], ['B', 'y']], [['A', 18], ['A', 'z']], [['C', 20], None]])

    def test_case_027(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_028(self):
        self.assertEqual(workflow.run({'entries': [['A', 20], ['B', 21], ['A', 28], ['C', 22], ['B', 27]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 20], ['A', 'x']], [['B', 21], ['B', 'y']], [['A', 20], ['A', 'z']], [['C', 22], None]])

    def test_case_029(self):
        self.assertEqual(workflow.run({'entries': [['A', 29], ['B', 30], ['A', 37], ['C', 31], ['B', 36]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 29], ['A', 'x']], [['B', 30], ['B', 'y']], [['A', 29], ['A', 'z']], [['C', 31], None]])

    def test_case_030(self):
        self.assertEqual(workflow.run({'entries': [['A', 12], ['B', 13], ['A', 20], ['C', 14], ['B', 19]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 12], ['A', 'x']], [['B', 13], ['B', 'y']], [['A', 12], ['A', 'z']], [['C', 14], None]])

    def test_case_031(self):
        self.assertEqual(workflow.run({'entries': [['A', 11], ['B', 12], ['A', 19], ['C', 13], ['B', 18]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 11], ['A', 'x']], [['B', 12], ['B', 'y']], [['A', 11], ['A', 'z']], [['C', 13], None]])

    def test_case_032(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

if __name__ == '__main__':
    unittest.main()
