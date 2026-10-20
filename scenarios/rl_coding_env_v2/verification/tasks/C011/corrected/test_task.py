"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import inflection as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser19_identifier_id']), 'Information http user19 identifier ids')

    def test_case_002(self):
        self.assertEqual(m.singularize('movie series'), 'movie series')

    def test_case_003(self):
        self.assertEqual(m.tableize('SalesMan'), 'sales_men')

    def test_case_004(self):
        self.assertEqual(m.ordinalize(-12), '-12th')

    def test_case_005(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser14_identifier_id']), 'Rice http user14 identifier ids')

    def test_case_006(self):
        self.assertEqual(m.parameterize('Hello...World', separator='.'), 'hello.world')

    def test_case_007(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')

    def test_case_008(self):
        self.assertEqual(m.transliterate('ﬂower'), 'flower')

    def test_case_009(self):
        self.assertEqual([m.ordinal(x) for x in [11,112,213,-111]], ['th', 'th', 'th', 'th'])

    def test_case_010(self):
        self.assertEqual(m.camelize('api_response_code', False), 'apiResponseCode')

    def test_case_011(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser20_identifier_id']), 'Rice http user20 identifier ids')

    def test_case_012(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser28_identifier_id']), 'Information http user28 identifier ids')

    def test_case_013(self):
        self.assertEqual(m.titleize('TheManWithoutAPast'), 'The Man Without A Past')

    def test_case_014(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser5_identifier_id']), 'Rice http user5 identifier ids')

    def test_case_015(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser22_identifier_id']), 'Information http user22 identifier ids')

    def test_case_016(self):
        self.assertEqual(m.pluralize('EQUIPMENT'), 'EQUIPMENT')

    def test_case_017(self):
        self.assertEqual(m.tableize('BusinessPerson'), 'business_people')

    def test_case_018(self):
        self.assertEqual(m.humanize('author_identity_id'), 'Author identity')

    def test_case_019(self):
        self.assertEqual(m.camelize('HTTP_error', False), 'hTTPError')

    def test_case_020(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser12_identifier_id']), 'Equipment http user12 identifier ids')

    def test_case_021(self):
        self.assertEqual(m.humanize('grid_id_number'), 'Grid id number')

    def test_case_022(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser25_identifier_id']), 'Information http user25 identifier ids')

    def test_case_023(self):
        self.assertEqual(m.parameterize('A ++ B', separator='+'), 'a+b')

    def test_case_024(self):
        self.assertEqual(m.titleize('HTTPServerError'), 'Http Server Error')

    def test_case_025(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')

    def test_case_026(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser7_identifier_id']), 'Information http user7 identifier ids')

    def test_case_027(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser10_identifier_id']), 'Information http user10 identifier ids')

    def test_case_028(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser6_identifier_id']), 'Equipment http user6 identifier ids')

    def test_case_029(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser2_identifier_id']), 'Rice http user2 identifier ids')

    def test_case_030(self):
        self.assertEqual(m.ordinalize(-21), '-21st')

    def test_case_031(self):
        self.assertEqual(m.pluralize('Information'), 'Information')

    def test_case_032(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser27_identifier_id']), 'Equipment http user27 identifier ids')

if __name__ == '__main__':
    unittest.main()
