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
        self.assertEqual(workflow.run({'count': 3, 'items': ['A7', 'B7', 'A7', 'C7', 'A7', 'B7', 'D7']}), [['A7', 3], ['B7', 2], ['D7', 1]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A26', 'B26', 'A26', 'C26', 'A26', 'B26', 'D26']}), [['A26', 3], ['B26', 2]])

    def test_case_004(self):
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_005(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_006(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A9', 'B9', 'A9', 'C9', 'A9', 'B9', 'D9']}), [['A9', 3], ['B9', 2], ['D9', 1]])

    def test_case_007(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_008(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_009(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_010(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A14', 'B14', 'A14', 'C14', 'A14', 'B14', 'D14']}), [['A14', 3], ['B14', 2]])

    def test_case_011(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A6', 'B6', 'A6', 'C6', 'A6', 'B6', 'D6']}), [['A6', 3], ['B6', 2]])

    def test_case_012(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A18', 'B18', 'A18', 'C18', 'A18', 'B18', 'D18']}), [['A18', 3], ['B18', 2]])

    def test_case_013(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_014(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A16', 'B16', 'A16', 'C16', 'A16', 'B16', 'D16']}), [['A16', 3], ['B16', 2]])

    def test_case_015(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_016(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_017(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A8', 'B8', 'A8', 'C8', 'A8', 'B8', 'D8']}), [['A8', 3], ['B8', 2]])

    def test_case_018(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A5', 'B5', 'A5', 'C5', 'A5', 'B5', 'D5']}), [['A5', 3], ['B5', 2], ['D5', 1]])

    def test_case_019(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_020(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A5', 'B5', 'A5', 'C5', 'A5', 'B5', 'D5']}), [['A5', 3], ['B5', 2], ['D5', 1]])

    def test_case_022(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A15', 'B15', 'A15', 'C15', 'A15', 'B15', 'D15']}), [['A15', 3], ['B15', 2], ['D15', 1]])

    def test_case_023(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_024(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_025(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_026(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_027(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_028(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_029(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

    def test_case_030(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A11', 'B11', 'A11', 'C11', 'A11', 'B11', 'D11']}), [['A11', 3], ['B11', 2], ['D11', 1]])

    def test_case_031(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A27', 'B27', 'A27', 'C27', 'A27', 'B27', 'D27']}), [['A27', 3], ['B27', 2], ['D27', 1]])

    def test_case_032(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

if __name__ == '__main__':
    unittest.main()
