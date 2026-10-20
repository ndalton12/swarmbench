"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import inflection as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_tableize_01(self):
        self.assertEqual(m.tableize('SalesPerson'), 'sales_people')

    def test_tableize_02(self):
        self.assertEqual(m.tableize('fancyCategory'), 'fancy_categories')

    def test_regression_camelize_03(self):
        self.assertEqual(m.camelize('order_line_item', False), 'orderLineItem')

    def test_regression_humanize_04(self):
        self.assertEqual(m.humanize('user_identifier'), 'User identifier')

    def test_regression_ordinal_05(self):
        self.assertEqual([m.ordinal(x) for x in [-12,23,1001,1013]], ['th', 'rd', 'st', 'th'])

    def test_regression_ordinalize_06(self):
        self.assertEqual(m.ordinalize(-103), '-103rd')

    def test_regression_parameterize_07(self):
        self.assertEqual(m.parameterize(' One|Two! ', separator='|'), 'one|two')

    def test_regression_pluralize_08(self):
        self.assertEqual(m.pluralize('RICE'), 'RICE')

    def test_regression_singularize_09(self):
        self.assertEqual(m.singularize('designerjeans'), 'designerjean')

    def test_regression_titleize_10(self):
        self.assertEqual(m.titleize('orderLineItem'), 'Order Line Item')

    def test_regression_transliterate_11(self):
        self.assertEqual(m.transliterate('naïve résumé'), 'naive resume')

    def test_regression_underscore_12(self):
        self.assertEqual(m.underscore('JSONResponseID'), 'json_response_id')

    def test_regression_dasherize_13(self):
        self.assertEqual(m.dasherize('a_b_c_d'), 'a-b-c-d')

if __name__ == '__main__':
    unittest.main()
