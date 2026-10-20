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
        self.assertEqual(list(m.difference([])), [])

    def test_case_002(self):
        self.assertEqual(workflow.run({'items': ['015', '016', '018', '019', '022', '023'], 'threshold': 18}), [[['015', '016']], [['018', '019'], ['022', '023']]])

    def test_case_003(self):
        self.assertEqual(workflow.run({'items': ['006', '007', '009', '010', '013', '014'], 'threshold': 9}), [[['006', '007']], [['009', '010'], ['013', '014']]])

    def test_case_004(self):
        self.assertEqual(workflow.run({'items': ['003', '004', '006', '007', '010', '011'], 'threshold': 6}), [[['003', '004']], [['006', '007'], ['010', '011']]])

    def test_case_005(self):
        self.assertEqual(list(m.always_iterable(7)), [7])

    def test_case_006(self):
        self.assertEqual(workflow.run({'items': ['001', '002', '004', '005', '008', '009'], 'threshold': 4}), [[['001', '002']], [['004', '005'], ['008', '009']]])

    def test_case_007(self):
        self.assertEqual(list(m.chunked(range(5), 3)), [[0, 1, 2], [3, 4]])

    def test_case_008(self):
        self.assertEqual(m.is_sorted(['long','mid','x'], key=len, reverse=True), True)

    def test_case_009(self):
        self.assertEqual(workflow.run({'items': ['005', '006', '008', '009', '012', '013'], 'threshold': 8}), [[['005', '006']], [['008', '009'], ['012', '013']]])

    def test_case_010(self):
        self.assertEqual(list(m.windowed('ab', 4, fillvalue='X')), [('a', 'b', 'X', 'X')])

    def test_case_011(self):
        self.assertEqual(list(m.split_after('a,b,c', lambda x:x==',', maxsplit=1)), [['a', ','], ['b', ',', 'c']])

    def test_case_012(self):
        self.assertEqual(list(m.windowed(range(8), 3, step=5, fillvalue=-1)), [(0, 1, 2), (5, 6, 7)])

    def test_case_013(self):
        self.assertEqual(workflow.run({'items': ['029', '030', '032', '033', '036', '037'], 'threshold': 32}), [[['029', '030']], [['032', '033'], ['036', '037']]])

    def test_case_014(self):
        self.assertEqual(list(m.split_before('aBcD', str.isupper, maxsplit=1)), [['a'], ['B', 'c', 'D']])

    def test_case_015(self):
        self.assertEqual(list(m.difference([5,3,-1])), [5, -2, -4])

    def test_case_016(self):
        self.assertEqual(list(m.padded(iter('abc'), 'X', 1)), ['a', 'b', 'c'])

    def test_case_017(self):
        self.assertEqual(workflow.run({'items': ['028', '029', '031', '032', '035', '036'], 'threshold': 31}), [[['028', '029']], [['031', '032'], ['035', '036']]])

    def test_case_018(self):
        self.assertEqual(list(m.padded([1,2,3], 0, 2, next_multiple=True)), [1, 2, 3, 0])

    def test_case_019(self):
        self.assertEqual(workflow.run({'items': ['023', '024', '026', '027', '030', '031'], 'threshold': 26}), [[['023', '024']], [['026', '027'], ['030', '031']]])

    def test_case_020(self):
        self.assertEqual(workflow.run({'items': ['021', '022', '024', '025', '028', '029'], 'threshold': 24}), [[['021', '022']], [['024', '025'], ['028', '029']]])

    def test_case_021(self):
        self.assertEqual([list(x) for x in m.divide(2, iter('abcde'))], [['a', 'b', 'c'], ['d', 'e']])

    def test_case_022(self):
        self.assertEqual([list(x) for x in m.distribute(2, iter('abcde'))], [['a', 'c', 'e'], ['b', 'd']])

    def test_case_023(self):
        self.assertEqual(list(m.split_at([1,0,2,0,3], lambda x:x==0, maxsplit=1, keep_separator=True)), [[1], [0], [2, 0, 3]])

    def test_case_024(self):
        self.assertEqual(workflow.run({'items': ['017', '018', '020', '021', '024', '025'], 'threshold': 20}), [[['017', '018']], [['020', '021'], ['024', '025']]])

    def test_case_025(self):
        self.assertEqual(workflow.run({'items': ['010', '011', '013', '014', '017', '018'], 'threshold': 13}), [[['010', '011']], [['013', '014'], ['017', '018']]])

    def test_case_026(self):
        self.assertEqual(workflow.run({'items': ['011', '012', '014', '015', '018', '019'], 'threshold': 14}), [[['011', '012']], [['014', '015'], ['018', '019']]])

    def test_case_027(self):
        self.assertEqual(raises(lambda: list(m.chunked(iter('abc'), 2, strict=True)), ValueError), True)

    def test_case_028(self):
        self.assertEqual([list(x) for x in m.consecutive_groups(['01','02','05'], ordering=int)], [['01', '02'], ['05']])

    def test_case_029(self):
        self.assertEqual(workflow.run({'items': ['030', '031', '033', '034', '037', '038'], 'threshold': 33}), [[['030', '031']], [['033', '034'], ['037', '038']]])

    def test_case_030(self):
        self.assertEqual(list(m.replace([2,2], lambda x:x==2, [0], count=0)), [2, 2])

    def test_case_031(self):
        self.assertEqual(list(m.replace('ababx', lambda a,b:a=='a' and b=='b', ['Z'], count=1, window_size=2)), ['Z', 'a', 'b', 'x'])

    def test_case_032(self):
        self.assertEqual(list(m.always_iterable('hello')), ['hello'])

if __name__ == '__main__':
    unittest.main()
