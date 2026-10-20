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
        self.assertEqual(m.pluralize('person'), 'people')

    def test_case_002(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_003(self):
        self.assertEqual(workflow.run('APIEvent_identity_id'), {'caption': 'Api event identity', 'heading': 'Api Event Identity'})

    def test_case_004(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_005(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_006(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_007(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_008(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_009(self):
        self.assertEqual(workflow.run('CSVExport_identity_id'), {'caption': 'Csv export identity', 'heading': 'Csv Export Identity'})

    def test_case_010(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_011(self):
        self.assertEqual(workflow.run('HTTPReport_identifier_id'), {'caption': 'Http report identifier', 'heading': 'Http Report Identifier'})

    def test_case_012(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_case_013(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_014(self):
        self.assertEqual(workflow.run('APIField_id_number'), {'caption': 'Api field id number', 'heading': 'Api Field Id Number'})

    def test_case_015(self):
        self.assertEqual(workflow.run('XMLProject_identity_id'), {'caption': 'Xml project identity', 'heading': 'Xml Project Identity'})

    def test_case_016(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_017(self):
        self.assertEqual(workflow.run('APIModel_identifier_id'), {'caption': 'Api model identifier', 'heading': 'Api Model Identifier'})

    def test_case_018(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_019(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_020(self):
        self.assertEqual(workflow.run('HTTPDevice_identity_id'), {'caption': 'Http device identity', 'heading': 'Http Device Identity'})

    def test_case_021(self):
        self.assertEqual(workflow.run('JSONInvoice_id_number'), {'caption': 'Json invoice id number', 'heading': 'Json Invoice Id Number'})

    def test_case_022(self):
        self.assertEqual(workflow.run('XMLBilling_identity_id'), {'caption': 'Xml billing identity', 'heading': 'Xml Billing Identity'})

    def test_case_023(self):
        self.assertEqual(workflow.run('HTTPServer_grid_id_code'), {'caption': 'Http server grid id code', 'heading': 'Http Server Grid Id Code'})

    def test_case_024(self):
        self.assertEqual(workflow.run('XMLContact_identifier_id'), {'caption': 'Xml contact identifier', 'heading': 'Xml Contact Identifier'})

    def test_case_025(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_026(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_027(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_028(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_029(self):
        self.assertEqual(workflow.run('HTTPList_id_label'), {'caption': 'Http list id label', 'heading': 'Http List Id Label'})

    def test_case_030(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_case_031(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_032(self):
        self.assertEqual(workflow.run('APIRecord_id_number'), {'caption': 'Api record id number', 'heading': 'Api Record Id Number'})

if __name__ == '__main__':
    unittest.main()
