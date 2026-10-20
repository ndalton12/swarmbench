"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import more_itertools as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle'], 'limit': 0, 'step': 5, 'width': 4}), [['start', 'private', 'value', 'middle']])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value', 'end'], 'limit': 1, 'step': 5, 'width': 4}), [['start', 'redacted', 'middle', 'private'], ['end', 'pad', 'pad', 'pad']])

    def test_case_003(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_004(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_005(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value'], 'limit': 0, 'step': 4, 'width': 3}), [['start', 'private', 'value'], ['private', 'value', 'pad']])

    def test_case_006(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_007(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value'], 'limit': 0, 'step': 4, 'width': 3}), [['start', 'private', 'value']])

    def test_case_008(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value'], 'limit': 2, 'step': 5, 'width': 4}), [['start', 'redacted', 'middle', 'redacted']])

    def test_case_009(self):
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_010(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_011(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_012(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle'], 'limit': 1, 'step': 4, 'width': 3}), [['start', 'redacted', 'middle']])

    def test_case_013(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_014(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value', 'end'], 'limit': 0, 'step': 4, 'width': 3}), [['start', 'private', 'value'], ['private', 'value', 'end']])

    def test_case_015(self):
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_016(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private'], 'limit': 1, 'step': 4, 'width': 3}), [['start', 'redacted', 'middle']])

    def test_case_018(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value'], 'limit': 0, 'step': 5, 'width': 4}), [['start', 'private', 'value', 'middle'], ['value', 'pad', 'pad', 'pad']])

    def test_case_019(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_020(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_021(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_022(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_023(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

    def test_case_024(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_case_025(self):
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_case_026(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value'], 'limit': 1, 'step': 5, 'width': 4}), [['start', 'redacted', 'middle', 'private']])

    def test_case_027(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_028(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_case_029(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_030(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private'], 'limit': 2, 'step': 4, 'width': 3}), [['start', 'redacted', 'middle']])

    def test_case_031(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private', 'value'], 'limit': 1, 'step': 4, 'width': 3}), [['start', 'redacted', 'middle'], ['value', 'pad', 'pad']])

    def test_case_032(self):
        self.assertEqual(workflow.run({'items': ['start', 'private', 'value', 'middle', 'private'], 'limit': 2, 'step': 5, 'width': 4}), [['start', 'redacted', 'middle', 'private']])

if __name__ == '__main__':
    unittest.main()
