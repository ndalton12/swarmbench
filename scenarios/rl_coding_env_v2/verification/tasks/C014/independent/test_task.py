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
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_002(self):
        self.assertEqual(workflow.run({'opening': 107, 'readings': [17, 23, 20, 27, 26]}), [107, 101, 104, 97, 98])

    def test_case_003(self):
        self.assertEqual(workflow.run({'opening': 101, 'readings': [11, 17, 14, 21, 20]}), [101, 95, 98, 91, 92])

    def test_case_004(self):
        self.assertEqual(workflow.run({'opening': 103, 'readings': [13, 19, 16, 23, 22]}), [103, 97, 100, 93, 94])

    def test_case_005(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_case_006(self):
        self.assertEqual(workflow.run({'opening': 127, 'readings': [37, 43, 40, 47, 46]}), [127, 121, 124, 117, 118])

    def test_case_007(self):
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_case_008(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

    def test_case_009(self):
        self.assertEqual(workflow.run({'opening': 121, 'readings': [31, 37, 34, 41, 40]}), [121, 115, 118, 111, 112])

    def test_case_010(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_011(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_012(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_013(self):
        self.assertEqual(workflow.run({'opening': 108, 'readings': [18, 24, 21, 28, 27]}), [108, 102, 105, 98, 99])

    def test_case_014(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_015(self):
        self.assertEqual(workflow.run({'opening': 115, 'readings': [25, 31, 28, 35, 34]}), [115, 109, 112, 105, 106])

    def test_case_016(self):
        self.assertEqual(workflow.run({'opening': 124, 'readings': [34, 40, 37, 44, 43]}), [124, 118, 121, 114, 115])

    def test_case_017(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_case_018(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_019(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_020(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_021(self):
        self.assertEqual(workflow.run({'opening': 117, 'readings': [27, 33, 30, 37, 36]}), [117, 111, 114, 107, 108])

    def test_case_022(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_023(self):
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_024(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_case_025(self):
        self.assertEqual(workflow.run({'opening': 111, 'readings': [21, 27, 24, 31, 30]}), [111, 105, 108, 101, 102])

    def test_case_026(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_027(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_028(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_029(self):
        self.assertEqual(workflow.run({'opening': 114, 'readings': [24, 30, 27, 34, 33]}), [114, 108, 111, 104, 105])

    def test_case_030(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_031(self):
        self.assertEqual(workflow.run({'opening': 100, 'readings': [10, 16, 13, 20, 19]}), [100, 94, 97, 90, 91])

    def test_case_032(self):
        self.assertEqual(workflow.run({'opening': 122, 'readings': [32, 38, 35, 42, 41]}), [122, 116, 119, 112, 113])

if __name__ == '__main__':
    unittest.main()
