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
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_002(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_003(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_004(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_005(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_006(self):
        self.assertEqual(workflow.run('JSONGroup2Bluejeans'), 'json-group2-bluejean')

    def test_case_007(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_008(self):
        self.assertEqual(m.pluralize('person'), 'people')

    def test_case_009(self):
        self.assertEqual(workflow.run('APIGroup3Bluejeans'), 'api-group3-bluejean')

    def test_case_010(self):
        self.assertEqual(workflow.run('XMLGroup1Bluejeans'), 'xml-group1-bluejean')

    def test_case_011(self):
        self.assertEqual(workflow.run('CSVGroup14Bluejeans'), 'csv-group14-bluejean')

    def test_case_012(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_case_013(self):
        self.assertEqual(workflow.run('APIGroup28Bluejeans'), 'api-group28-bluejean')

    def test_case_014(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_015(self):
        self.assertEqual(workflow.run('JSONGroup22Bluejeans'), 'json-group22-bluejean')

    def test_case_016(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_017(self):
        self.assertEqual(workflow.run('APIGroup8Bluejeans'), 'api-group8-bluejean')

    def test_case_018(self):
        self.assertEqual(workflow.run('CSVGroup4Bluejeans'), 'csv-group4-bluejean')

    def test_case_019(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_020(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_021(self):
        self.assertEqual(workflow.run('APIGroup23Bluejeans'), 'api-group23-bluejean')

    def test_case_022(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_023(self):
        self.assertEqual(workflow.run('XMLGroup16Bluejeans'), 'xml-group16-bluejean')

    def test_case_024(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_025(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_026(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_027(self):
        self.assertEqual(workflow.run('XMLGroup26Bluejeans'), 'xml-group26-bluejean')

    def test_case_028(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_029(self):
        self.assertEqual(workflow.run('JSONGroup17Bluejeans'), 'json-group17-bluejean')

    def test_case_030(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_031(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_case_032(self):
        self.assertEqual(workflow.run('XMLGroup6Bluejeans'), 'xml-group6-bluejean')

if __name__ == '__main__':
    unittest.main()
