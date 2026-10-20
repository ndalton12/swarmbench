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
        self.assertEqual(workflow.run('JSONRéponseRésumé27Item'), 'json+reponse+resume27+item')

    def test_case_002(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_003(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_004(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_005(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_006(self):
        self.assertEqual(workflow.run('XMLRéponseRésumé21Item'), 'xml+reponse+resume21+item')

    def test_case_007(self):
        self.assertEqual(workflow.run('HTTPRéponseRésumé5Item'), 'http+reponse+resume5+item')

    def test_case_008(self):
        self.assertEqual(workflow.run('APIRéponseRésumé8Item'), 'api+reponse+resume8+item')

    def test_case_009(self):
        self.assertEqual(m.pluralize('person'), 'people')

    def test_case_010(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_011(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_012(self):
        self.assertEqual(workflow.run('APIRéponseRésumé13Item'), 'api+reponse+resume13+item')

    def test_case_013(self):
        self.assertEqual(workflow.run('HTTPRéponseRésumé20Item'), 'http+reponse+resume20+item')

    def test_case_014(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_015(self):
        self.assertEqual(workflow.run('APIRéponseRésumé28Item'), 'api+reponse+resume28+item')

    def test_case_016(self):
        self.assertEqual(workflow.run('HTTPRéponseRésumé0Item'), 'http+reponse+resume0+item')

    def test_case_017(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_018(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_019(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_020(self):
        self.assertEqual(workflow.run('XMLRéponseRésumé16Item'), 'xml+reponse+resume16+item')

    def test_case_021(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_022(self):
        self.assertEqual(workflow.run('HTTPRéponseRésumé25Item'), 'http+reponse+resume25+item')

    def test_case_023(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_024(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_025(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_026(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_case_027(self):
        self.assertEqual(workflow.run('APIRéponseRésumé3Item'), 'api+reponse+resume3+item')

    def test_case_028(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_029(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_case_030(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_031(self):
        self.assertEqual(workflow.run('HTTPRéponseRésumé10Item'), 'http+reponse+resume10+item')

    def test_case_032(self):
        self.assertEqual(workflow.run('CSVRéponseRésumé14Item'), 'csv+reponse+resume14+item')

if __name__ == '__main__':
    unittest.main()
