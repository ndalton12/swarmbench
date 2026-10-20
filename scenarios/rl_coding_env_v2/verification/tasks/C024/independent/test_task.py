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
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_002(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_003(self):
        self.assertEqual(workflow.run({'entries': [['A', 9], ['B', 10], ['A', 17], ['C', 11], ['B', 16]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 9], ['A', 'x']], [['B', 10], ['B', 'y']], [['A', 9], ['A', 'z']], [['C', 11], None]])

    def test_case_004(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_005(self):
        self.assertEqual(workflow.run({'entries': [['A', 6], ['B', 7], ['A', 14], ['C', 8], ['B', 13]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 6], ['A', 'x']], [['B', 7], ['B', 'y']], [['A', 6], ['A', 'z']], [['C', 8], None]])

    def test_case_006(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_007(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_008(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_009(self):
        self.assertEqual(workflow.run({'entries': [['A', 13], ['B', 14], ['A', 21], ['C', 15], ['B', 20]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 13], ['A', 'x']], [['B', 14], ['B', 'y']], [['A', 13], ['A', 'z']], [['C', 15], None]])

    def test_case_010(self):
        self.assertEqual(workflow.run({'entries': [['A', 17], ['B', 18], ['A', 25], ['C', 19], ['B', 24]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 17], ['A', 'x']], [['B', 18], ['B', 'y']], [['A', 17], ['A', 'z']], [['C', 19], None]])

    def test_case_011(self):
        self.assertEqual(workflow.run({'entries': [['A', 22], ['B', 23], ['A', 30], ['C', 24], ['B', 29]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 22], ['A', 'x']], [['B', 23], ['B', 'y']], [['A', 22], ['A', 'z']], [['C', 24], None]])

    def test_case_012(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_013(self):
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_014(self):
        self.assertEqual(workflow.run({'entries': [['A', 28], ['B', 29], ['A', 36], ['C', 30], ['B', 35]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 28], ['A', 'x']], [['B', 29], ['B', 'y']], [['A', 28], ['A', 'z']], [['C', 30], None]])

    def test_case_015(self):
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_016(self):
        self.assertEqual(workflow.run({'entries': [['A', 5], ['B', 6], ['A', 13], ['C', 7], ['B', 12]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 5], ['A', 'x']], [['B', 6], ['B', 'y']], [['A', 5], ['A', 'z']], [['C', 7], None]])

    def test_case_017(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_018(self):
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_case_019(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

    def test_case_020(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_case_021(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_022(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_023(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_case_024(self):
        self.assertEqual(workflow.run({'entries': [['A', 2], ['B', 3], ['A', 10], ['C', 4], ['B', 9]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 2], ['A', 'x']], [['B', 3], ['B', 'y']], [['A', 2], ['A', 'z']], [['C', 4], None]])

    def test_case_025(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_026(self):
        self.assertEqual(workflow.run({'entries': [['A', 15], ['B', 16], ['A', 23], ['C', 17], ['B', 22]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 15], ['A', 'x']], [['B', 16], ['B', 'y']], [['A', 15], ['A', 'z']], [['C', 17], None]])

    def test_case_027(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_028(self):
        self.assertEqual(workflow.run({'entries': [['A', 14], ['B', 15], ['A', 22], ['C', 16], ['B', 21]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 14], ['A', 'x']], [['B', 15], ['B', 'y']], [['A', 14], ['A', 'z']], [['C', 16], None]])

    def test_case_029(self):
        self.assertEqual(workflow.run({'entries': [['A', 3], ['B', 4], ['A', 11], ['C', 5], ['B', 10]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 3], ['A', 'x']], [['B', 4], ['B', 'y']], [['A', 3], ['A', 'z']], [['C', 5], None]])

    def test_case_030(self):
        self.assertEqual(workflow.run({'entries': [['A', 7], ['B', 8], ['A', 15], ['C', 9], ['B', 14]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 7], ['A', 'x']], [['B', 8], ['B', 'y']], [['A', 7], ['A', 'z']], [['C', 9], None]])

    def test_case_031(self):
        self.assertEqual(workflow.run({'entries': [['A', 10], ['B', 11], ['A', 18], ['C', 12], ['B', 17]], 'lookup': [['A', 'x'], ['B', 'y'], ['A', 'z']]}), [[['A', 10], ['A', 'x']], [['B', 11], ['B', 'y']], [['A', 10], ['A', 'z']], [['C', 12], None]])

    def test_case_032(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

if __name__ == '__main__':
    unittest.main()
