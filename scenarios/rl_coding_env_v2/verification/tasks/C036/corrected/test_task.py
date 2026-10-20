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
        self.assertEqual(list(m.padded([1,2,3,4], None, 2)), [1, 2, 3, 4])

    def test_case_003(self):
        self.assertEqual(raises(lambda: list(m.chunked(range(5), 3, strict=True)), ValueError), True)

    def test_case_004(self):
        self.assertEqual(list(m.windowed(range(4), 2, step=4)), [(0, 1)])

    def test_case_005(self):
        self.assertEqual(workflow.run({'items': ['017', '018', '019', '022', '023', '026'], 'length': 3}), [[['017', '018', '019']], [['022', '023'], ['026']]])

    def test_case_006(self):
        self.assertEqual(list(m.windowed([1], 3, fillvalue=0)), [(1, 0, 0)])

    def test_case_007(self):
        self.assertEqual(workflow.run({'items': ['018', '019', '020', '023', '024', '027'], 'length': 3}), [[['018', '019', '020']], [['023', '024'], ['027']]])

    def test_case_008(self):
        self.assertEqual(workflow.run({'items': ['006', '007', '008', '011', '012', '015'], 'length': 3}), [[['006', '007', '008']], [['011', '012'], ['015']]])

    def test_case_009(self):
        self.assertEqual(workflow.run({'items': ['013', '014', '015', '018', '019', '022'], 'length': 3}), [[['013', '014', '015']], [['018', '019'], ['022']]])

    def test_case_010(self):
        self.assertEqual([list(x) for x in m.divide(3, range(8))], [[0, 1, 2], [3, 4, 5], [6, 7]])

    def test_case_011(self):
        self.assertEqual(list(m.difference([2,5,9], initial=0)), [3, 4])

    def test_case_012(self):
        self.assertEqual(list(m.split_at('a,b,c', lambda x:x==',', maxsplit=1)), [['a'], ['b', ',', 'c']])

    def test_case_013(self):
        self.assertEqual([list(x) for x in m.distribute(3, range(8))], [[0, 3, 6], [1, 4, 7], [2, 5]])

    def test_case_014(self):
        self.assertEqual(workflow.run({'items': ['022', '023', '024', '027', '028', '031'], 'length': 3}), [[['022', '023', '024']], [['027', '028'], ['031']]])

    def test_case_015(self):
        self.assertEqual(workflow.run({'items': ['007', '008', '009', '012', '013', '016'], 'length': 3}), [[['007', '008', '009']], [['012', '013'], ['016']]])

    def test_case_016(self):
        self.assertEqual(list(m.chunked(range(6), 3, strict=True)), [[0, 1, 2], [3, 4, 5]])

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': ['011', '012', '013', '016', '017', '020'], 'length': 3}), [[['011', '012', '013']], [['016', '017'], ['020']]])

    def test_case_018(self):
        self.assertEqual(list(m.always_iterable('ab', base_type=None)), ['a', 'b'])

    def test_case_019(self):
        self.assertEqual(list(m.windowed(range(5), 2, step=4, fillvalue=-1)), [(0, 1), (4, -1)])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': ['004', '005', '006', '009', '010', '013'], 'length': 3}), [[['004', '005', '006']], [['009', '010'], ['013']]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'items': ['003', '004', '005', '008', '009', '012'], 'length': 3}), [[['003', '004', '005']], [['008', '009'], ['012']]])

    def test_case_022(self):
        self.assertEqual(list(m.always_iterable('abc')), ['abc'])

    def test_case_023(self):
        self.assertEqual(workflow.run({'items': ['019', '020', '021', '024', '025', '028'], 'length': 3}), [[['019', '020', '021']], [['024', '025'], ['028']]])

    def test_case_024(self):
        self.assertEqual(list(m.difference([10,13,12,20])), [10, 3, -1, 8])

    def test_case_025(self):
        self.assertEqual(workflow.run({'items': ['008', '009', '010', '013', '014', '017'], 'length': 3}), [[['008', '009', '010']], [['013', '014'], ['017']]])

    def test_case_026(self):
        self.assertEqual([list(x) for x in m.divide(4, [1,2])], [[1], [2], [], []])

    def test_case_027(self):
        self.assertEqual(workflow.run({'items': ['027', '028', '029', '032', '033', '036'], 'length': 3}), [[['027', '028', '029']], [['032', '033'], ['036']]])

    def test_case_028(self):
        self.assertEqual(workflow.run({'items': ['015', '016', '017', '020', '021', '024'], 'length': 3}), [[['015', '016', '017']], [['020', '021'], ['024']]])

    def test_case_029(self):
        self.assertEqual(list(m.padded([1], 0, 3)), [1, 0, 0])

    def test_case_030(self):
        self.assertEqual(list(m.split_before([1,2,3,4], lambda x:x%2==0, maxsplit=1)), [[1], [2, 3, 4]])

    def test_case_031(self):
        self.assertEqual(list(m.always_iterable(b'ab')), [b'ab'])

    def test_case_032(self):
        self.assertEqual([list(x) for x in m.consecutive_groups('abdefg', ordering=ord)], [['a', 'b'], ['d', 'e', 'f', 'g']])

if __name__ == '__main__':
    unittest.main()
