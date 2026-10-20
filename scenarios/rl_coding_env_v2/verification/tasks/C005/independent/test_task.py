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
        self.assertEqual(workflow.run('naïve_identifier_20_id'), {'label': 'Naive identifier 20', 'slug': 'naive+identifier+20'})

    def test_case_002(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_003(self):
        self.assertEqual(m.pluralize('person'), 'people')

    def test_case_004(self):
        self.assertEqual(workflow.run('élève_identifier_21_id'), {'label': 'Eleve identifier 21', 'slug': 'eleve+identifier+21'})

    def test_case_005(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_006(self):
        self.assertEqual(workflow.run('naïve_identifier_26_id'), {'label': 'Naive identifier 26', 'slug': 'naive+identifier+26'})

    def test_case_007(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_008(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_009(self):
        self.assertEqual(workflow.run('résumé_identifier_18_id'), {'label': 'Resume identifier 18', 'slug': 'resume+identifier+18'})

    def test_case_010(self):
        self.assertEqual(workflow.run('Málaga_identifier_1_id'), {'label': 'Malaga identifier 1', 'slug': 'malaga+identifier+1'})

    def test_case_011(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_case_012(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_013(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_014(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_015(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_016(self):
        self.assertEqual(workflow.run('naïve_identifier_8_id'), {'label': 'Naive identifier 8', 'slug': 'naive+identifier+8'})

    def test_case_017(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_018(self):
        self.assertEqual(workflow.run('café_identifier_16_id'), {'label': 'Cafe identifier 16', 'slug': 'cafe+identifier+16'})

    def test_case_019(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_020(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_021(self):
        self.assertEqual(workflow.run('ﬂower_identifier_23_id'), {'label': 'Flower identifier 23', 'slug': 'flower+identifier+23'})

    def test_case_022(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_023(self):
        self.assertEqual(workflow.run('ﬂower_identifier_29_id'), {'label': 'Flower identifier 29', 'slug': 'flower+identifier+29'})

    def test_case_024(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_025(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_026(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_027(self):
        self.assertEqual(workflow.run('naïve_identifier_2_id'), {'label': 'Naive identifier 2', 'slug': 'naive+identifier+2'})

    def test_case_028(self):
        self.assertEqual(workflow.run('ﬂower_identifier_11_id'), {'label': 'Flower identifier 11', 'slug': 'flower+identifier+11'})

    def test_case_029(self):
        self.assertEqual(workflow.run('café_identifier_10_id'), {'label': 'Cafe identifier 10', 'slug': 'cafe+identifier+10'})

    def test_case_030(self):
        self.assertEqual(workflow.run('café_identifier_22_id'), {'label': 'Cafe identifier 22', 'slug': 'cafe+identifier+22'})

    def test_case_031(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_032(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

if __name__ == '__main__':
    unittest.main()
