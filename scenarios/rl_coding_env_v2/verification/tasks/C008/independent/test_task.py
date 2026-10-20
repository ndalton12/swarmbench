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
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_case_003(self):
        self.assertEqual(workflow.run('Sales11Person'), {'collection': 'sales11People', 'table': 'sales11_people'})

    def test_case_004(self):
        self.assertEqual(workflow.run('Billing28Person'), {'collection': 'billing28People', 'table': 'billing28_people'})

    def test_case_005(self):
        self.assertEqual(m.singularize('posts'), 'post')

    def test_case_006(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_case_007(self):
        self.assertEqual(m.titleize('raiders_of_the_lost_ark'), 'Raiders Of The Lost Ark')

    def test_case_008(self):
        self.assertEqual(m.parameterize('Málaga!', separator=''), 'malaga')

    def test_case_009(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_case_010(self):
        self.assertEqual(workflow.run('Support17Person'), {'collection': 'support17People', 'table': 'support17_people'})

    def test_case_011(self):
        self.assertEqual(workflow.run('Business10Person'), {'collection': 'business10People', 'table': 'business10_people'})

    def test_case_012(self):
        self.assertEqual(workflow.run('Support2Person'), {'collection': 'support2People', 'table': 'support2_people'})

    def test_case_013(self):
        self.assertEqual(workflow.run('Business25Person'), {'collection': 'business25People', 'table': 'business25_people'})

    def test_case_014(self):
        self.assertEqual(workflow.run('Support27Person'), {'collection': 'support27People', 'table': 'support27_people'})

    def test_case_015(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_case_016(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_case_017(self):
        self.assertEqual(workflow.run('Billing3Person'), {'collection': 'billing3People', 'table': 'billing3_people'})

    def test_case_018(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_case_019(self):
        self.assertEqual(m.transliterate('① test'), '1 test')

    def test_case_020(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_case_021(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_case_022(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_case_023(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_case_024(self):
        self.assertEqual(workflow.run('Business15Person'), {'collection': 'business15People', 'table': 'business15_people'})

    def test_case_025(self):
        self.assertEqual(workflow.run('Support7Person'), {'collection': 'support7People', 'table': 'support7_people'})

    def test_case_026(self):
        self.assertEqual(workflow.run('Business5Person'), {'collection': 'business5People', 'table': 'business5_people'})

    def test_case_027(self):
        self.assertEqual(m.camelize('device_type'), 'DeviceType')

    def test_case_028(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_case_029(self):
        self.assertEqual(m.ordinalize(111), '111th')

    def test_case_030(self):
        self.assertEqual(workflow.run('Billing13Person'), {'collection': 'billing13People', 'table': 'billing13_people'})

    def test_case_031(self):
        self.assertEqual(m.humanize('EMPLOYEE_salary'), 'Employee salary')

    def test_case_032(self):
        self.assertEqual(workflow.run('Contact14Person'), {'collection': 'contact14People', 'table': 'contact14_people'})

if __name__ == '__main__':
    unittest.main()
