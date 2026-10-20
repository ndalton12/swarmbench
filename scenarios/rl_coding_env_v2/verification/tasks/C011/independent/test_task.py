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
        self.assertEqual(workflow.run(['RICE', 'HTTPUser11_identifier_id']), 'Rice http user11 identifier ids')

    def test_case_002(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_003(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_004(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_005(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser13_identifier_id']), 'Information http user13 identifier ids')

    def test_case_006(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_007(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_008(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_009(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_case_010(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_011(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser23_identifier_id']), 'Rice http user23 identifier ids')

    def test_case_012(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser21_identifier_id']), 'Equipment http user21 identifier ids')

    def test_case_013(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_014(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser29_identifier_id']), 'Rice http user29 identifier ids')

    def test_case_015(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser18_identifier_id']), 'Equipment http user18 identifier ids')

    def test_case_016(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_017(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_018(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_case_019(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_020(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser16_identifier_id']), 'Information http user16 identifier ids')

    def test_case_021(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_022(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser0_identifier_id']), 'Equipment http user0 identifier ids')

    def test_case_023(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_024(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_025(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_026(self):
        self.assertEqual(workflow.run(['RICE', 'HTTPUser8_identifier_id']), 'Rice http user8 identifier ids')

    def test_case_027(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser24_identifier_id']), 'Equipment http user24 identifier ids')

    def test_case_028(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser3_identifier_id']), 'Equipment http user3 identifier ids')

    def test_case_029(self):
        self.assertEqual(workflow.run(['INFORMATION', 'HTTPUser4_identifier_id']), 'Information http user4 identifier ids')

    def test_case_030(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_031(self):
        self.assertEqual(m.pluralize('person'), 'people')

    def test_case_032(self):
        self.assertEqual(workflow.run(['EQUIPMENT', 'HTTPUser15_identifier_id']), 'Equipment http user15 identifier ids')

if __name__ == '__main__':
    unittest.main()
