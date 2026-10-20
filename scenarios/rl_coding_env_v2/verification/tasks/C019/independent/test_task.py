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
        self.assertEqual(workflow.run(['A19', 'B19', 'a19', 'C19', 'b19', 'A19']), [['A19', 3], ['B19', 2], ['C19', 1]])

    def test_case_003(self):
        self.assertEqual(workflow.run(['A8', 'B8', 'a8', 'C8', 'b8', 'A8']), [['A8', 3], ['B8', 2], ['C8', 1]])

    def test_case_004(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_005(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_case_006(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_case_007(self):
        self.assertEqual(workflow.run(['A16', 'B16', 'a16', 'C16', 'b16', 'A16']), [['A16', 3], ['B16', 2], ['C16', 1]])

    def test_case_008(self):
        self.assertEqual(workflow.run(['A14', 'B14', 'a14', 'C14', 'b14', 'A14']), [['A14', 3], ['B14', 2], ['C14', 1]])

    def test_case_009(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

    def test_case_010(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_011(self):
        self.assertEqual(workflow.run(['A3', 'B3', 'a3', 'C3', 'b3', 'A3']), [['A3', 3], ['B3', 2], ['C3', 1]])

    def test_case_012(self):
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_013(self):
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_014(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_015(self):
        self.assertEqual(workflow.run(['A15', 'B15', 'a15', 'C15', 'b15', 'A15']), [['A15', 3], ['B15', 2], ['C15', 1]])

    def test_case_016(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_017(self):
        self.assertEqual(workflow.run(['A20', 'B20', 'a20', 'C20', 'b20', 'A20']), [['A20', 3], ['B20', 2], ['C20', 1]])

    def test_case_018(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_019(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_020(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_021(self):
        self.assertEqual(workflow.run(['A12', 'B12', 'a12', 'C12', 'b12', 'A12']), [['A12', 3], ['B12', 2], ['C12', 1]])

    def test_case_022(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_023(self):
        self.assertEqual(workflow.run(['A0', 'B0', 'a0', 'C0', 'b0', 'A0']), [['A0', 3], ['B0', 2], ['C0', 1]])

    def test_case_024(self):
        self.assertEqual(workflow.run(['A25', 'B25', 'a25', 'C25', 'b25', 'A25']), [['A25', 3], ['B25', 2], ['C25', 1]])

    def test_case_025(self):
        self.assertEqual(workflow.run(['A17', 'B17', 'a17', 'C17', 'b17', 'A17']), [['A17', 3], ['B17', 2], ['C17', 1]])

    def test_case_026(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_027(self):
        self.assertEqual(workflow.run(['A29', 'B29', 'a29', 'C29', 'b29', 'A29']), [['A29', 3], ['B29', 2], ['C29', 1]])

    def test_case_028(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_029(self):
        self.assertEqual(workflow.run(['A11', 'B11', 'a11', 'C11', 'b11', 'A11']), [['A11', 3], ['B11', 2], ['C11', 1]])

    def test_case_030(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_031(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_032(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

if __name__ == '__main__':
    unittest.main()
