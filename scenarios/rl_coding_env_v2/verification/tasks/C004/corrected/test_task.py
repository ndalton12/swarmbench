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
        self.assertEqual(m.tableize('SalesMan'), 'sales_men')

    def test_case_002(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')

    def test_case_003(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')

    def test_case_004(self):
        self.assertEqual(workflow.run({'rank': -41, 'section': 'account_line_2_item'}), 'account-line-2-item+-41st')

    def test_case_005(self):
        self.assertEqual(workflow.run({'rank': -301, 'section': 'account_line_28_item'}), 'account-line-28-item+-301st')

    def test_case_006(self):
        self.assertEqual(workflow.run({'rank': -171, 'section': 'account_line_15_item'}), 'account-line-15-item+-171st')

    def test_case_007(self):
        self.assertEqual(m.tableize('BusinessPerson'), 'business_people')

    def test_case_008(self):
        self.assertEqual(workflow.run({'rank': -81, 'section': 'account_line_6_item'}), 'account-line-6-item+-81st')

    def test_case_009(self):
        self.assertEqual(m.humanize('author_identity_id'), 'Author identity')

    def test_case_010(self):
        self.assertEqual(m.titleize('HTTPServerError'), 'Http Server Error')

    def test_case_011(self):
        self.assertEqual(m.parameterize('Hello...World', separator='.'), 'hello.world')

    def test_case_012(self):
        self.assertEqual(workflow.run({'rank': -271, 'section': 'account_line_25_item'}), 'account-line-25-item+-271st')

    def test_case_013(self):
        self.assertEqual(m.humanize('grid_id_number'), 'Grid id number')

    def test_case_014(self):
        self.assertEqual(workflow.run({'rank': -211, 'section': 'account_line_19_item'}), 'account-line-19-item+-211th')

    def test_case_015(self):
        self.assertEqual(workflow.run({'rank': -201, 'section': 'account_line_18_item'}), 'account-line-18-item+-201st')

    def test_case_016(self):
        self.assertEqual(m.camelize('api_response_code', False), 'apiResponseCode')

    def test_case_017(self):
        self.assertEqual(m.singularize('movie series'), 'movie series')

    def test_case_018(self):
        self.assertEqual(m.pluralize('EQUIPMENT'), 'EQUIPMENT')

    def test_case_019(self):
        self.assertEqual(m.ordinalize(-21), '-21st')

    def test_case_020(self):
        self.assertEqual(workflow.run({'rank': -101, 'section': 'account_line_8_item'}), 'account-line-8-item+-101st')

    def test_case_021(self):
        self.assertEqual(m.titleize('TheManWithoutAPast'), 'The Man Without A Past')

    def test_case_022(self):
        self.assertEqual(workflow.run({'rank': -261, 'section': 'account_line_24_item'}), 'account-line-24-item+-261st')

    def test_case_023(self):
        self.assertEqual(m.camelize('HTTP_error', False), 'hTTPError')

    def test_case_024(self):
        self.assertEqual(m.transliterate('ﬂower'), 'flower')

    def test_case_025(self):
        self.assertEqual(m.ordinalize(-12), '-12th')

    def test_case_026(self):
        self.assertEqual(workflow.run({'rank': -111, 'section': 'account_line_9_item'}), 'account-line-9-item+-111th')

    def test_case_027(self):
        self.assertEqual(workflow.run({'rank': -61, 'section': 'account_line_4_item'}), 'account-line-4-item+-61st')

    def test_case_028(self):
        self.assertEqual(m.pluralize('Information'), 'Information')

    def test_case_029(self):
        self.assertEqual(workflow.run({'rank': -281, 'section': 'account_line_26_item'}), 'account-line-26-item+-281st')

    def test_case_030(self):
        self.assertEqual(m.parameterize('A ++ B', separator='+'), 'a+b')

    def test_case_031(self):
        self.assertEqual(workflow.run({'rank': -271, 'section': 'account_line_25_item'}), 'account-line-25-item+-271st')

    def test_case_032(self):
        self.assertEqual([m.ordinal(x) for x in [11,112,213,-111]], ['th', 'th', 'th', 'th'])

if __name__ == '__main__':
    unittest.main()
