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
        self.assertEqual(list(m.sliding_window(3, [1,2,3,4])), [(1, 2, 3), (2, 3, 4)])

    def test_case_002(self):
        self.assertEqual(list(m.unique([[1],[1],[2]], key=tuple)), [[1], [2]])

    def test_case_003(self):
        self.assertEqual(list(m.accumulate(operator.sub, [2,3], 20)), [20, 18, 15])

    def test_case_004(self):
        self.assertEqual(m.tail(2, iter([1,2,3,4])), (3, 4))

    def test_case_005(self):
        self.assertEqual(m.get([], [1,2]), ())

    def test_case_006(self):
        self.assertEqual(list(m.interpose('-', ['a','b','c'])), ['a', '-', 'b', '-', 'c'])

    def test_case_007(self):
        self.assertEqual(list(m.partition_all(3, [1,2,3,4,5])), [(1, 2, 3), (4, 5)])

    def test_case_008(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[1, 2, 3, 4], [], [101], [201, 202]]}), [[1, 101, 201, 2], [202, 3, 4]])

    def test_case_009(self):
        self.assertEqual(list(m.unique(['a','A','b','B'], key=str.lower)), ['a', 'b'])

    def test_case_010(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[5, 6, 7, 8], [], [105], [205, 206]]}), [[5, 105, 205, 6], [206, 7, 8]])

    def test_case_011(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[27, 28, 29, 30], [], [127], [227, 228]]}), [[27, 127, 227, 28], [228, 29, 30]])

    def test_case_012(self):
        self.assertEqual(list(m.interleave([[],[4,5]])), [4, 5])

    def test_case_013(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[19, 20, 21, 22], [], [119], [219, 220]]}), [[19, 119, 219, 20], [220, 21, 22]])

    def test_case_014(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[15, 16, 17, 18], [], [115], [215, 216]]}), [[15, 115, 215, 16], [216, 17, 18]])

    def test_case_015(self):
        self.assertEqual(workflow.run({'size': 3, 'streams': [[16, 17, 18, 19], [], [116], [216, 217]]}), [[16, 116, 216], [17, 217, 18], [19]])

    def test_case_016(self):
        self.assertEqual(list(m.interpose(0, [7])), [7])

    def test_case_017(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[29, 30, 31, 32], [], [129], [229, 230]]}), [[29, 129, 229, 30], [230, 31, 32]])

    def test_case_018(self):
        self.assertEqual(m.get([1], ['a','b','c']), ('b',))

    def test_case_019(self):
        self.assertEqual(m.reduceby(lambda x: x%2, operator.add, [1,2,3,4], 0), {1: 4, 0: 6})

    def test_case_020(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[3, 4, 5, 6], [], [103], [203, 204]]}), [[3, 103, 203, 4], [204, 5, 6]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'size': 3, 'streams': [[24, 25, 26, 27], [], [124], [224, 225]]}), [[24, 124, 224], [25, 225, 26], [27]])

    def test_case_022(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[17, 18, 19, 20], [], [117], [217, 218]]}), [[17, 117, 217, 18], [218, 19, 20]])

    def test_case_023(self):
        self.assertEqual(list(m.accumulate(operator.sub, [10,2,3])), [10, 8, 5])

    def test_case_024(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[25, 26, 27, 28], [], [125], [225, 226]]}), [[25, 125, 225, 26], [226, 27, 28]])

    def test_case_025(self):
        self.assertEqual(workflow.run({'size': 3, 'streams': [[22, 23, 24, 25], [], [122], [222, 223]]}), [[22, 122, 222], [23, 223, 24], [25]])

    def test_case_026(self):
        self.assertEqual(m.reduceby(lambda x:x[0], lambda a,b:a+[b], ['ab','ac','bc'], list), {'a': ['ab', 'ac'], 'b': ['bc']})

    def test_case_027(self):
        self.assertEqual(m.frequencies(iter([2,2,3,2])), {2: 3, 3: 1})

    def test_case_028(self):
        self.assertEqual(list(m.interleave([[1,2,3], [10], [20,21]])), [1, 10, 20, 2, 21, 3])

    def test_case_029(self):
        self.assertEqual(list(m.sliding_window(2, iter('abc'))), [('a', 'b'), ('b', 'c')])

    def test_case_030(self):
        self.assertEqual(workflow.run({'size': 4, 'streams': [[11, 12, 13, 14], [], [111], [211, 212]]}), [[11, 111, 211, 12], [212, 13, 14]])

    def test_case_031(self):
        self.assertEqual(m.tail(4, iter([1,2])), (1, 2))

    def test_case_032(self):
        self.assertEqual(m.frequencies('banana'), {'b': 1, 'a': 3, 'n': 2})

if __name__ == '__main__':
    unittest.main()
