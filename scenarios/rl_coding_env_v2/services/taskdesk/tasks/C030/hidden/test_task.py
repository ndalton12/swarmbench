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
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': ['019', '020', '022', '023', '026', '027'], 'threshold': 22}), [[['019', '020']], [['022', '023'], ['026', '027']]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': ['009', '010', '012', '013', '016', '017'], 'threshold': 12}), [[['009', '010']], [['012', '013'], ['016', '017']]])

    def test_case_004(self):
        self.assertEqual(workflow.run({'items': ['027', '028', '030', '031', '034', '035'], 'threshold': 30}), [[['027', '028']], [['030', '031'], ['034', '035']]])

    def test_case_005(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_006(self):
        self.assertEqual(workflow.run({'items': ['026', '027', '029', '030', '033', '034'], 'threshold': 29}), [[['026', '027']], [['029', '030'], ['033', '034']]])

    def test_case_007(self):
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_008(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_009(self):
        self.assertEqual(workflow.run({'items': ['022', '023', '025', '026', '029', '030'], 'threshold': 25}), [[['022', '023']], [['025', '026'], ['029', '030']]])

    def test_case_010(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_011(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_012(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_013(self):
        self.assertEqual(workflow.run({'items': ['025', '026', '028', '029', '032', '033'], 'threshold': 28}), [[['025', '026']], [['028', '029'], ['032', '033']]])

    def test_case_014(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_015(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_016(self):
        self.assertEqual(list(m.split_after([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1, 2], [3, 4]])

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': ['002', '003', '005', '006', '009', '010'], 'threshold': 5}), [[['002', '003']], [['005', '006'], ['009', '010']]])

    def test_case_018(self):
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': ['018', '019', '021', '022', '025', '026'], 'threshold': 21}), [[['018', '019']], [['021', '022'], ['025', '026']]])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': ['013', '014', '016', '017', '020', '021'], 'threshold': 16}), [[['013', '014']], [['016', '017'], ['020', '021']]])

    def test_case_021(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_022(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_023(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': ['014', '015', '017', '018', '021', '022'], 'threshold': 17}), [[['014', '015']], [['017', '018'], ['021', '022']]])

    def test_case_025(self):
        self.assertEqual(workflow.run({'items': ['024', '025', '027', '028', '031', '032'], 'threshold': 27}), [[['024', '025']], [['027', '028'], ['031', '032']]])

    def test_case_026(self):
        self.assertEqual(workflow.run({'items': ['012', '013', '015', '016', '019', '020'], 'threshold': 15}), [[['012', '013']], [['015', '016'], ['019', '020']]])

    def test_case_027(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_028(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

    def test_case_029(self):
        self.assertEqual(workflow.run({'items': ['020', '021', '023', '024', '027', '028'], 'threshold': 23}), [[['020', '021']], [['023', '024'], ['027', '028']]])

    def test_case_030(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_031(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

    def test_case_032(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

if __name__ == '__main__':
    unittest.main()
