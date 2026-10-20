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
        self.assertEqual(m.titleize('TheManWithoutAPast'), 'The Man Without A Past')

    def test_case_003(self):
        self.assertEqual(workflow.run('Sales1Person'), {'collection': 'sales1People', 'table': 'sales1_people'})

    def test_case_004(self):
        self.assertEqual(workflow.run('Contact9Person'), {'collection': 'contact9People', 'table': 'contact9_people'})

    def test_case_005(self):
        self.assertEqual(m.singularize('movie series'), 'movie series')

    def test_case_006(self):
        self.assertEqual(m.camelize('api_response_code', False), 'apiResponseCode')

    def test_case_007(self):
        self.assertEqual(m.titleize('HTTPServerError'), 'Http Server Error')

    def test_case_008(self):
        self.assertEqual(m.parameterize('A ++ B', separator='+'), 'a+b')

    def test_case_009(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')

    def test_case_010(self):
        self.assertEqual(workflow.run('Sales16Person'), {'collection': 'sales16People', 'table': 'sales16_people'})

    def test_case_011(self):
        self.assertEqual(workflow.run('Contact29Person'), {'collection': 'contact29People', 'table': 'contact29_people'})

    def test_case_012(self):
        self.assertEqual(workflow.run('Billing8Person'), {'collection': 'billing8People', 'table': 'billing8_people'})

    def test_case_013(self):
        self.assertEqual(workflow.run('Support12Person'), {'collection': 'support12People', 'table': 'support12_people'})

    def test_case_014(self):
        self.assertEqual(workflow.run('Business0Person'), {'collection': 'business0People', 'table': 'business0_people'})

    def test_case_015(self):
        self.assertEqual(m.pluralize('EQUIPMENT'), 'EQUIPMENT')

    def test_case_016(self):
        self.assertEqual(m.tableize('SalesMan'), 'sales_men')

    def test_case_017(self):
        self.assertEqual(workflow.run('Sales6Person'), {'collection': 'sales6People', 'table': 'sales6_people'})

    def test_case_018(self):
        self.assertEqual(m.tableize('BusinessPerson'), 'business_people')

    def test_case_019(self):
        self.assertEqual(m.transliterate('ﬂower'), 'flower')

    def test_case_020(self):
        self.assertEqual(m.parameterize('Hello...World', separator='.'), 'hello.world')

    def test_case_021(self):
        self.assertEqual(m.humanize('author_identity_id'), 'Author identity')

    def test_case_022(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')

    def test_case_023(self):
        self.assertEqual([m.ordinal(x) for x in [11,112,213,-111]], ['th', 'th', 'th', 'th'])

    def test_case_024(self):
        self.assertEqual(workflow.run('Support22Person'), {'collection': 'support22People', 'table': 'support22_people'})

    def test_case_025(self):
        self.assertEqual(workflow.run('Sales26Person'), {'collection': 'sales26People', 'table': 'sales26_people'})

    def test_case_026(self):
        self.assertEqual(workflow.run('Contact4Person'), {'collection': 'contact4People', 'table': 'contact4_people'})

    def test_case_027(self):
        self.assertEqual(m.camelize('HTTP_error', False), 'hTTPError')

    def test_case_028(self):
        self.assertEqual(m.ordinalize(-21), '-21st')

    def test_case_029(self):
        self.assertEqual(m.ordinalize(-12), '-12th')

    def test_case_030(self):
        self.assertEqual(workflow.run('Business20Person'), {'collection': 'business20People', 'table': 'business20_people'})

    def test_case_031(self):
        self.assertEqual(m.humanize('grid_id_number'), 'Grid id number')

    def test_case_032(self):
        self.assertEqual(workflow.run('Sales21Person'), {'collection': 'sales21People', 'table': 'sales21_people'})

if __name__ == '__main__':
    unittest.main()
