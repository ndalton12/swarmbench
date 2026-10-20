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
    def test_ordinal_01(self):
        self.assertEqual([m.ordinal(x) for x in [11,112,213,-111]], ['th', 'th', 'th', 'th'])

    def test_regression_camelize_02(self):
        self.assertEqual(m.camelize('api_response_code', False), 'apiResponseCode')

    def test_regression_humanize_03(self):
        self.assertEqual(m.humanize('author_identity_id'), 'Author identity')

    def test_regression_ordinalize_04(self):
        self.assertEqual(m.ordinalize(-21), '-21st')

    def test_regression_parameterize_05(self):
        self.assertEqual(m.parameterize('Hello...World', separator='.'), 'hello.world')

    def test_regression_pluralize_06(self):
        self.assertEqual(m.pluralize('EQUIPMENT'), 'EQUIPMENT')

    def test_regression_singularize_07(self):
        self.assertEqual(m.singularize('bluejeans'), 'bluejean')

    def test_regression_tableize_08(self):
        self.assertEqual(m.tableize('BusinessPerson'), 'business_people')

    def test_regression_titleize_09(self):
        self.assertEqual(m.titleize('TheManWithoutAPast'), 'The Man Without A Past')

    def test_regression_transliterate_10(self):
        self.assertEqual(m.transliterate('Málaga café'), 'Malaga cafe')

    def test_regression_underscore_11(self):
        self.assertEqual(m.underscore('HTTPServerError'), 'http_server_error')

    def test_regression_dasherize_12(self):
        self.assertEqual(m.dasherize('account_line_item'), 'account-line-item')

if __name__ == '__main__':
    unittest.main()
