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
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_002(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_003(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_004(self):
        self.assertEqual(workflow.run({'rank': -71, 'section': 'account_line_5_item'}), 'account-line-5-item+-71st')

    def test_case_005(self):
        self.assertEqual(workflow.run({'rank': -141, 'section': 'account_line_12_item'}), 'account-line-12-item+-141st')

    def test_case_006(self):
        self.assertEqual(workflow.run({'rank': -191, 'section': 'account_line_17_item'}), 'account-line-17-item+-191st')

    def test_case_007(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_008(self):
        self.assertEqual(workflow.run({'rank': -231, 'section': 'account_line_21_item'}), 'account-line-21-item+-231st')

    def test_case_009(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_case_010(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_011(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_012(self):
        self.assertEqual(workflow.run({'rank': -311, 'section': 'account_line_29_item'}), 'account-line-29-item+-311th')

    def test_case_013(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_014(self):
        self.assertEqual(workflow.run({'rank': -251, 'section': 'account_line_23_item'}), 'account-line-23-item+-251st')

    def test_case_015(self):
        self.assertEqual(workflow.run({'rank': -221, 'section': 'account_line_20_item'}), 'account-line-20-item+-221st')

    def test_case_016(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_017(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_018(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_019(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_020(self):
        self.assertEqual(workflow.run({'rank': -121, 'section': 'account_line_10_item'}), 'account-line-10-item+-121st')

    def test_case_021(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_022(self):
        self.assertEqual(workflow.run({'rank': -51, 'section': 'account_line_3_item'}), 'account-line-3-item+-51st')

    def test_case_023(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_024(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_025(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_026(self):
        self.assertEqual(workflow.run({'rank': -291, 'section': 'account_line_27_item'}), 'account-line-27-item+-291st')

    def test_case_027(self):
        self.assertEqual(workflow.run({'rank': -21, 'section': 'account_line_0_item'}), 'account-line-0-item+-21st')

    def test_case_028(self):
        self.assertEqual(m.pluralize('person'), 'people')

    def test_case_029(self):
        self.assertEqual(workflow.run({'rank': -131, 'section': 'account_line_11_item'}), 'account-line-11-item+-131st')

    def test_case_030(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_031(self):
        self.assertEqual(workflow.run({'rank': -31, 'section': 'account_line_1_item'}), 'account-line-1-item+-31st')

    def test_case_032(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

if __name__ == '__main__':
    unittest.main()
