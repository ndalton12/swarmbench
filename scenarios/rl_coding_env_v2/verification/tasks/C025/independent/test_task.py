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
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_case_002(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A28', 'B28', 'A28', 'C28', 'A28', 'B28', 'D28']}), [['A28', 3], ['B28', 2]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A17', 'B17', 'A17', 'C17', 'A17', 'B17', 'D17']}), [['A17', 3], ['B17', 2], ['D17', 1]])

    def test_case_004(self):
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_005(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_006(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A24', 'B24', 'A24', 'C24', 'A24', 'B24', 'D24']}), [['A24', 3], ['B24', 2]])

    def test_case_007(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_008(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_009(self):
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_010(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A1', 'B1', 'A1', 'C1', 'A1', 'B1', 'D1']}), [['A1', 3], ['B1', 2], ['D1', 1]])

    def test_case_011(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A19', 'B19', 'A19', 'C19', 'A19', 'B19', 'D19']}), [['A19', 3], ['B19', 2], ['D19', 1]])

    def test_case_012(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A10', 'B10', 'A10', 'C10', 'A10', 'B10', 'D10']}), [['A10', 3], ['B10', 2]])

    def test_case_013(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_014(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A22', 'B22', 'A22', 'C22', 'A22', 'B22', 'D22']}), [['A22', 3], ['B22', 2]])

    def test_case_015(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_case_016(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_017(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A23', 'B23', 'A23', 'C23', 'A23', 'B23', 'D23']}), [['A23', 3], ['B23', 2], ['D23', 1]])

    def test_case_018(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A3', 'B3', 'A3', 'C3', 'A3', 'B3', 'D3']}), [['A3', 3], ['B3', 2], ['D3', 1]])

    def test_case_019(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_case_020(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_021(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A20', 'B20', 'A20', 'C20', 'A20', 'B20', 'D20']}), [['A20', 3], ['B20', 2]])

    def test_case_022(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A12', 'B12', 'A12', 'C12', 'A12', 'B12', 'D12']}), [['A12', 3], ['B12', 2]])

    def test_case_023(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_case_024(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_025(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_026(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_027(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_028(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_029(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_030(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A21', 'B21', 'A21', 'C21', 'A21', 'B21', 'D21']}), [['A21', 3], ['B21', 2], ['D21', 1]])

    def test_case_031(self):
        self.assertEqual(workflow.run({'count': 2, 'items': ['A4', 'B4', 'A4', 'C4', 'A4', 'B4', 'D4']}), [['A4', 3], ['B4', 2]])

    def test_case_032(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

if __name__ == '__main__':
    unittest.main()
