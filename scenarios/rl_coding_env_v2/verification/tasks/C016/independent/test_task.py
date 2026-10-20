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
        self.assertEqual(list(m.partition_all(3, iter(range(5)))), [(0, 1, 2), (3, 4)])

    def test_case_002(self):
        self.assertEqual(list(m.interpose(None, iter([1,2]))), [1, None, 2])

    def test_case_003(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[12, 13, 14, 15, 16, 17], [], [112, 113], [212]]}), [15, 16, 17])

    def test_case_004(self):
        self.assertEqual(list(m.partition_all(2, list(range(7)))), [(0, 1), (2, 3), (4, 5), (6,)])

    def test_case_005(self):
        self.assertEqual(m.get([0,3], [5], None), (5, None))

    def test_case_006(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[21, 22, 23, 24, 25, 26], [], [121, 122], [221]]}), [23, 24, 25, 26])

    def test_case_007(self):
        self.assertEqual(list(m.sliding_window(4, range(3))), [])

    def test_case_008(self):
        self.assertEqual(list(m.accumulate(lambda a,b: a+'/'+b, ['a','b','c'])), ['a', 'a/b', 'a/b/c'])

    def test_case_009(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[26, 27, 28, 29, 30, 31], [], [126, 127], [226]]}), [29, 30, 31])

    def test_case_010(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[15, 16, 17, 18, 19, 20], [], [115, 116], [215]]}), [17, 18, 19, 20])

    def test_case_011(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[3, 4, 5, 6, 7, 8], [], [103, 104], [203]]}), [5, 6, 7, 8])

    def test_case_012(self):
        self.assertEqual(list(m.sliding_window(1, [9,8])), [(9,), (8,)])

    def test_case_013(self):
        self.assertEqual(list(m.join(0, [(1,'a')], 0, [(1,'x'),(3,'z')], left_default=None,right_default=None)), [((1, 'a'), (1, 'x')), (None, (3, 'z'))])

    def test_case_014(self):
        self.assertEqual(m.tail(3, (x*x for x in range(6))), (9, 16, 25))

    def test_case_015(self):
        self.assertEqual(m.frequencies([None,None,'x']), {None: 2, 'x': 1})

    def test_case_016(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[17, 18, 19, 20, 21, 22], [], [117, 118], [217]]}), [19, 20, 21, 22])

    def test_case_017(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[13, 14, 15, 16, 17, 18], [], [113, 114], [213]]}), [15, 16, 17, 18])

    def test_case_018(self):
        self.assertEqual(list(m.pluck([1,0,3], [[8,9]], default=None)), [(9, 8, None)])

    def test_case_019(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[19, 20, 21, 22, 23, 24], [], [119, 120], [219]]}), [21, 22, 23, 24])

    def test_case_020(self):
        self.assertEqual(m.tail(0, iter([1,2])), ())

    def test_case_021(self):
        self.assertEqual(m.reduceby(lambda x:x%3, operator.add, [1,4,2,5], 10), {1: 15, 2: 17})

    def test_case_022(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[9, 10, 11, 12, 13, 14], [], [109, 110], [209]]}), [11, 12, 13, 14])

    def test_case_023(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[22, 23, 24, 25, 26, 27], [], [122, 123], [222]]}), [25, 26, 27])

    def test_case_024(self):
        self.assertEqual(list(m.accumulate(operator.sub, [], 7)), [7])

    def test_case_025(self):
        self.assertEqual(list(m.unique(['Pear','PEAR','apple'], key=str.lower)), ['Pear', 'apple'])

    def test_case_026(self):
        self.assertEqual(list(m.interleave([iter('abc'), iter('X')])), ['a', 'X', 'b', 'c'])

    def test_case_027(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[5, 6, 7, 8, 9, 10], [], [105, 106], [205]]}), [7, 8, 9, 10])

    def test_case_028(self):
        self.assertEqual(m.get(['x'], {'x':7}), (7,))

    def test_case_029(self):
        self.assertEqual(workflow.run({'count': 4, 'streams': [[27, 28, 29, 30, 31, 32], [], [127, 128], [227]]}), [29, 30, 31, 32])

    def test_case_030(self):
        self.assertEqual(m.frequencies([]), {})

    def test_case_031(self):
        self.assertEqual(list(m.unique([1,2,1])), [1, 2])

    def test_case_032(self):
        self.assertEqual(workflow.run({'count': 3, 'streams': [[14, 15, 16, 17, 18, 19], [], [114, 115], [214]]}), [17, 18, 19])

if __name__ == '__main__':
    unittest.main()
