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
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_002(self):
        self.assertEqual(workflow.run({'entries': [['A', 5], ['B', 6], ['A', 7], ['C', 8]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 5], ['A', 2]], [['A', 7], ['A', 2]]], 'B': [[['B', 6], ['B', 3]]], 'C': [[['C', 8], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 24, 'B': 18, 'C': 8, 'D': 0}})

    def test_case_003(self):
        self.assertEqual(workflow.run({'entries': [['A', 24], ['B', 25], ['A', 26], ['C', 27]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 24], ['A', 2]], [['A', 26], ['A', 2]]], 'B': [[['B', 25], ['B', 3]]], 'C': [[['C', 27], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 100, 'B': 75, 'C': 27, 'D': 0}})

    def test_case_004(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_005(self):
        self.assertEqual(workflow.run({'entries': [['A', 13], ['B', 14], ['A', 15], ['C', 16]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 13], ['A', 2]], [['A', 15], ['A', 2]]], 'B': [[['B', 14], ['B', 3]]], 'C': [[['C', 16], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 56, 'B': 42, 'C': 16, 'D': 0}})

    def test_case_006(self):
        self.assertEqual(workflow.run({'entries': [['A', 9], ['B', 10], ['A', 11], ['C', 12]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 9], ['A', 2]], [['A', 11], ['A', 2]]], 'B': [[['B', 10], ['B', 3]]], 'C': [[['C', 12], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 40, 'B': 30, 'C': 12, 'D': 0}})

    def test_case_007(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_008(self):
        self.assertEqual(workflow.run({'entries': [['A', 21], ['B', 22], ['A', 23], ['C', 24]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 21], ['A', 2]], [['A', 23], ['A', 2]]], 'B': [[['B', 22], ['B', 3]]], 'C': [[['C', 24], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 88, 'B': 66, 'C': 24, 'D': 0}})

    def test_case_009(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_010(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_011(self):
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_012(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

    def test_case_013(self):
        self.assertEqual(workflow.run({'entries': [['A', 30], ['B', 31], ['A', 32], ['C', 33]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 30], ['A', 2]], [['A', 32], ['A', 2]]], 'B': [[['B', 31], ['B', 3]]], 'C': [[['C', 33], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 124, 'B': 93, 'C': 33, 'D': 0}})

    def test_case_014(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_015(self):
        self.assertEqual(workflow.run({'entries': [['A', 16], ['B', 17], ['A', 18], ['C', 19]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 16], ['A', 2]], [['A', 18], ['A', 2]]], 'B': [[['B', 17], ['B', 3]]], 'C': [[['C', 19], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 68, 'B': 51, 'C': 19, 'D': 0}})

    def test_case_016(self):
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_017(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_018(self):
        self.assertEqual(workflow.run({'entries': [['A', 18], ['B', 19], ['A', 20], ['C', 21]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 18], ['A', 2]], [['A', 20], ['A', 2]]], 'B': [[['B', 19], ['B', 3]]], 'C': [[['C', 21], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 76, 'B': 57, 'C': 21, 'D': 0}})

    def test_case_019(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_020(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_021(self):
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_case_022(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_case_023(self):
        self.assertEqual(workflow.run({'entries': [['A', 6], ['B', 7], ['A', 8], ['C', 9]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 6], ['A', 2]], [['A', 8], ['A', 2]]], 'B': [[['B', 7], ['B', 3]]], 'C': [[['C', 9], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 28, 'B': 21, 'C': 9, 'D': 0}})

    def test_case_024(self):
        self.assertEqual(workflow.run({'entries': [['A', 12], ['B', 13], ['A', 14], ['C', 15]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 12], ['A', 2]], [['A', 14], ['A', 2]]], 'B': [[['B', 13], ['B', 3]]], 'C': [[['C', 15], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 52, 'B': 39, 'C': 15, 'D': 0}})

    def test_case_025(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_026(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_027(self):
        self.assertEqual(workflow.run({'entries': [['A', 22], ['B', 23], ['A', 24], ['C', 25]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 22], ['A', 2]], [['A', 24], ['A', 2]]], 'B': [[['B', 23], ['B', 3]]], 'C': [[['C', 25], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 92, 'B': 69, 'C': 25, 'D': 0}})

    def test_case_028(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_case_029(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_case_030(self):
        self.assertEqual(workflow.run({'entries': [['A', 31], ['B', 32], ['A', 33], ['C', 34]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 31], ['A', 2]], [['A', 33], ['A', 2]]], 'B': [[['B', 32], ['B', 3]]], 'C': [[['C', 34], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 128, 'B': 96, 'C': 34, 'D': 0}})

    def test_case_031(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_032(self):
        self.assertEqual(workflow.run({'entries': [['A', 20], ['B', 21], ['A', 22], ['C', 23]], 'weights': [['A', 2], ['B', 3], ['D', 4]]}), {'members': {'A': [[['A', 20], ['A', 2]], [['A', 22], ['A', 2]]], 'B': [[['B', 21], ['B', 3]]], 'C': [[['C', 23], None]], 'D': [[None, ['D', 4]]]}, 'totals': {'A': 84, 'B': 63, 'C': 23, 'D': 0}})

if __name__ == '__main__':
    unittest.main()
