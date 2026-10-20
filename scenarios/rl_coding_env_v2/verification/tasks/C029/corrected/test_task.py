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
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_case_002(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_case_003(self):
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_004(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_005(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_006(self):
        self.assertEqual(workflow.run(['head28', 'escape', ',', 'middle28', ',', 'tail28', ',', 'end']), [['head28', 'literal-comma', 'middle28'], ['tail28', ',', 'end']])

    def test_case_007(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_008(self):
        self.assertEqual(workflow.run(['head4', 'escape', ',', 'middle4', ',', 'tail4', ',', 'end']), [['head4', 'literal-comma', 'middle4'], ['tail4', ',', 'end']])

    def test_case_009(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_010(self):
        self.assertEqual(workflow.run(['head20', 'escape', ',', 'middle20', ',', 'tail20', ',', 'end']), [['head20', 'literal-comma', 'middle20'], ['tail20', ',', 'end']])

    def test_case_011(self):
        self.assertEqual(workflow.run(['head23', 'escape', ',', 'middle23', ',', 'tail23', ',', 'end']), [['head23', 'literal-comma', 'middle23'], ['tail23', ',', 'end']])

    def test_case_012(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_013(self):
        self.assertEqual(workflow.run(['head0', 'escape', ',', 'middle0', ',', 'tail0', ',', 'end']), [['head0', 'literal-comma', 'middle0'], ['tail0', ',', 'end']])

    def test_case_014(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_015(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_case_016(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_017(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

    def test_case_018(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_019(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_020(self):
        self.assertEqual(workflow.run(['head5', 'escape', ',', 'middle5', ',', 'tail5', ',', 'end']), [['head5', 'literal-comma', 'middle5'], ['tail5', ',', 'end']])

    def test_case_021(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_022(self):
        self.assertEqual(workflow.run(['head3', 'escape', ',', 'middle3', ',', 'tail3', ',', 'end']), [['head3', 'literal-comma', 'middle3'], ['tail3', ',', 'end']])

    def test_case_023(self):
        self.assertEqual(workflow.run(['head26', 'escape', ',', 'middle26', ',', 'tail26', ',', 'end']), [['head26', 'literal-comma', 'middle26'], ['tail26', ',', 'end']])

    def test_case_024(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_025(self):
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_026(self):
        self.assertEqual(workflow.run(['head7', 'escape', ',', 'middle7', ',', 'tail7', ',', 'end']), [['head7', 'literal-comma', 'middle7'], ['tail7', ',', 'end']])

    def test_case_027(self):
        self.assertEqual(workflow.run(['head12', 'escape', ',', 'middle12', ',', 'tail12', ',', 'end']), [['head12', 'literal-comma', 'middle12'], ['tail12', ',', 'end']])

    def test_case_028(self):
        self.assertEqual(workflow.run(['head16', 'escape', ',', 'middle16', ',', 'tail16', ',', 'end']), [['head16', 'literal-comma', 'middle16'], ['tail16', ',', 'end']])

    def test_case_029(self):
        self.assertEqual(workflow.run(['head21', 'escape', ',', 'middle21', ',', 'tail21', ',', 'end']), [['head21', 'literal-comma', 'middle21'], ['tail21', ',', 'end']])

    def test_case_030(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_031(self):
        self.assertEqual(workflow.run(['head8', 'escape', ',', 'middle8', ',', 'tail8', ',', 'end']), [['head8', 'literal-comma', 'middle8'], ['tail8', ',', 'end']])

    def test_case_032(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

if __name__ == '__main__':
    unittest.main()
