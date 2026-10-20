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
        self.assertEqual(m.pluralize('Information'), 'Information')

    def test_case_002(self):
        self.assertEqual(m.tableize('SalesMan'), 'sales_men')

    def test_case_003(self):
        self.assertEqual(workflow.run('JSONOrder_identifier_id'), {'caption': 'Json order identifier', 'heading': 'Json Order Identifier'})

    def test_case_004(self):
        self.assertEqual(m.humanize('grid_id_number'), 'Grid id number')

    def test_case_005(self):
        self.assertEqual(m.parameterize('A ++ B', separator='+'), 'a+b')

    def test_case_006(self):
        self.assertEqual(m.titleize('TheManWithoutAPast'), 'The Man Without A Past')

    def test_case_007(self):
        self.assertEqual(m.ordinalize(-12), '-12th')

    def test_case_008(self):
        self.assertEqual(m.tableize('BusinessPerson'), 'business_people')

    def test_case_009(self):
        self.assertEqual(workflow.run('APIUser_id_token'), {'caption': 'Api user id token', 'heading': 'Api User Id Token'})

    def test_case_010(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')

    def test_case_011(self):
        self.assertEqual(workflow.run('CSVUser_identity_id'), {'caption': 'Csv user identity', 'heading': 'Csv User Identity'})

    def test_case_012(self):
        self.assertEqual(m.humanize('author_identity_id'), 'Author identity')

    def test_case_013(self):
        self.assertEqual(m.camelize('api_response_code', False), 'apiResponseCode')

    def test_case_014(self):
        self.assertEqual(workflow.run('CSVRecord_identifier_id'), {'caption': 'Csv record identifier', 'heading': 'Csv Record Identifier'})

    def test_case_015(self):
        self.assertEqual(workflow.run('APIResponse_identity_id'), {'caption': 'Api response identity', 'heading': 'Api Response Identity'})

    def test_case_016(self):
        self.assertEqual(m.camelize('HTTP_error', False), 'hTTPError')

    def test_case_017(self):
        self.assertEqual(workflow.run('HTTPEntry_identity_id'), {'caption': 'Http entry identity', 'heading': 'Http Entry Identity'})

    def test_case_018(self):
        self.assertEqual(m.pluralize('EQUIPMENT'), 'EQUIPMENT')

    def test_case_019(self):
        self.assertEqual(m.transliterate('ﬂower'), 'flower')

    def test_case_020(self):
        self.assertEqual(workflow.run('JSONAccount_identifier_id'), {'caption': 'Json account identifier', 'heading': 'Json Account Identifier'})

    def test_case_021(self):
        self.assertEqual(workflow.run('XMLAccount_id_number'), {'caption': 'Xml account id number', 'heading': 'Xml Account Id Number'})

    def test_case_022(self):
        self.assertEqual(workflow.run('JSONSchema_identifier_id'), {'caption': 'Json schema identifier', 'heading': 'Json Schema Identifier'})

    def test_case_023(self):
        self.assertEqual(workflow.run('XMLDevice_id_number'), {'caption': 'Xml device id number', 'heading': 'Xml Device Id Number'})

    def test_case_024(self):
        self.assertEqual(workflow.run('JSONColumn_identifier_id'), {'caption': 'Json column identifier', 'heading': 'Json Column Identifier'})

    def test_case_025(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')

    def test_case_026(self):
        self.assertEqual(m.singularize('movie series'), 'movie series')

    def test_case_027(self):
        self.assertEqual(m.parameterize('Hello...World', separator='.'), 'hello.world')

    def test_case_028(self):
        self.assertEqual(m.titleize('HTTPServerError'), 'Http Server Error')

    def test_case_029(self):
        self.assertEqual(workflow.run('CSVImport_identity_id'), {'caption': 'Csv import identity', 'heading': 'Csv Import Identity'})

    def test_case_030(self):
        self.assertEqual([m.ordinal(x) for x in [11,112,213,-111]], ['th', 'th', 'th', 'th'])

    def test_case_031(self):
        self.assertEqual(m.ordinalize(-21), '-21st')

    def test_case_032(self):
        self.assertEqual(workflow.run('HTTPMetric_id_label'), {'caption': 'Http metric id label', 'heading': 'Http Metric Id Label'})

if __name__ == '__main__':
    unittest.main()
