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
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_002(self):
        self.assertEqual(workflow.run(['A6', 'B6', 'a6', 'C6', 'b6', 'A6']), [['A6', 3], ['B6', 2], ['C6', 1]])

    def test_case_003(self):
        self.assertEqual(workflow.run(['A13', 'B13', 'a13', 'C13', 'b13', 'A13']), [['A13', 3], ['B13', 2], ['C13', 1]])

    def test_case_004(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_005(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_006(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_007(self):
        self.assertEqual(workflow.run(['A26', 'B26', 'a26', 'C26', 'b26', 'A26']), [['A26', 3], ['B26', 2], ['C26', 1]])

    def test_case_008(self):
        self.assertEqual(workflow.run(['A18', 'B18', 'a18', 'C18', 'b18', 'A18']), [['A18', 3], ['B18', 2], ['C18', 1]])

    def test_case_009(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_010(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_011(self):
        self.assertEqual(workflow.run(['A28', 'B28', 'a28', 'C28', 'b28', 'A28']), [['A28', 3], ['B28', 2], ['C28', 1]])

    def test_case_012(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_013(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_014(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_015(self):
        self.assertEqual(workflow.run(['A22', 'B22', 'a22', 'C22', 'b22', 'A22']), [['A22', 3], ['B22', 2], ['C22', 1]])

    def test_case_016(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_017(self):
        self.assertEqual(workflow.run(['A23', 'B23', 'a23', 'C23', 'b23', 'A23']), [['A23', 3], ['B23', 2], ['C23', 1]])

    def test_case_018(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_019(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_020(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_021(self):
        self.assertEqual(workflow.run(['A24', 'B24', 'a24', 'C24', 'b24', 'A24']), [['A24', 3], ['B24', 2], ['C24', 1]])

    def test_case_022(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_023(self):
        self.assertEqual(workflow.run(['A7', 'B7', 'a7', 'C7', 'b7', 'A7']), [['A7', 3], ['B7', 2], ['C7', 1]])

    def test_case_024(self):
        self.assertEqual(workflow.run(['A21', 'B21', 'a21', 'C21', 'b21', 'A21']), [['A21', 3], ['B21', 2], ['C21', 1]])

    def test_case_025(self):
        self.assertEqual(workflow.run(['A4', 'B4', 'a4', 'C4', 'b4', 'A4']), [['A4', 3], ['B4', 2], ['C4', 1]])

    def test_case_026(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_027(self):
        self.assertEqual(workflow.run(['A10', 'B10', 'a10', 'C10', 'b10', 'A10']), [['A10', 3], ['B10', 2], ['C10', 1]])

    def test_case_028(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_029(self):
        self.assertEqual(workflow.run(['A27', 'B27', 'a27', 'C27', 'b27', 'A27']), [['A27', 3], ['B27', 2], ['C27', 1]])

    def test_case_030(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_031(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_032(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

if __name__ == '__main__':
    unittest.main()
