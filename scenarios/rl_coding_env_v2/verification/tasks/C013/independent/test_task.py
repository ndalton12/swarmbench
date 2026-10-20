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
        self.assertEqual(workflow.run([{'group': 'A', 'value': 11}, {'group': 'B', 'value': 14}, {'group': 'a', 'value': 18}, {'group': 'C'}, {'group': 'b', 'value': 10}]), [['A', 11], ['B', 14], ['C', 0]])

    def test_case_002(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 28}, {'group': 'B', 'value': 31}, {'group': 'a', 'value': 35}, {'group': 'C'}, {'group': 'b', 'value': 27}]), [['A', 28], ['B', 31], ['C', 0]])

    def test_case_003(self):
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_case_004(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 15}, {'group': 'B', 'value': 18}, {'group': 'a', 'value': 22}, {'group': 'C'}, {'group': 'b', 'value': 14}]), [['A', 15], ['B', 18], ['C', 0]])

    def test_case_005(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_006(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 12}, {'group': 'B', 'value': 15}, {'group': 'a', 'value': 19}, {'group': 'C'}, {'group': 'b', 'value': 11}]), [['A', 12], ['B', 15], ['C', 0]])

    def test_case_007(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 23}, {'group': 'B', 'value': 26}, {'group': 'a', 'value': 30}, {'group': 'C'}, {'group': 'b', 'value': 22}]), [['A', 23], ['B', 26], ['C', 0]])

    def test_case_008(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_case_009(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_010(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_011(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_case_012(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_013(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 9}, {'group': 'B', 'value': 12}, {'group': 'a', 'value': 16}, {'group': 'C'}, {'group': 'b', 'value': 8}]), [['A', 9], ['B', 12], ['C', 0]])

    def test_case_014(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_015(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

    def test_case_016(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 16}, {'group': 'B', 'value': 19}, {'group': 'a', 'value': 23}, {'group': 'C'}, {'group': 'b', 'value': 15}]), [['A', 16], ['B', 19], ['C', 0]])

    def test_case_017(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_018(self):
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_019(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_020(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_021(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 31}, {'group': 'B', 'value': 34}, {'group': 'a', 'value': 38}, {'group': 'C'}, {'group': 'b', 'value': 30}]), [['A', 31], ['B', 34], ['C', 0]])

    def test_case_022(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_023(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 18}, {'group': 'B', 'value': 21}, {'group': 'a', 'value': 25}, {'group': 'C'}, {'group': 'b', 'value': 17}]), [['A', 18], ['B', 21], ['C', 0]])

    def test_case_024(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 20}, {'group': 'B', 'value': 23}, {'group': 'a', 'value': 27}, {'group': 'C'}, {'group': 'b', 'value': 19}]), [['A', 20], ['B', 23], ['C', 0]])

    def test_case_025(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 21}, {'group': 'B', 'value': 24}, {'group': 'a', 'value': 28}, {'group': 'C'}, {'group': 'b', 'value': 20}]), [['A', 21], ['B', 24], ['C', 0]])

    def test_case_026(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_027(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 24}, {'group': 'B', 'value': 27}, {'group': 'a', 'value': 31}, {'group': 'C'}, {'group': 'b', 'value': 23}]), [['A', 24], ['B', 27], ['C', 0]])

    def test_case_028(self):
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_029(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_030(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_031(self):
        self.assertEqual(workflow.run([{'group': 'A', 'value': 14}, {'group': 'B', 'value': 17}, {'group': 'a', 'value': 21}, {'group': 'C'}, {'group': 'b', 'value': 13}]), [['A', 14], ['B', 17], ['C', 0]])

    def test_case_032(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

if __name__ == '__main__':
    unittest.main()
