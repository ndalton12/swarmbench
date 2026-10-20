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
        self.assertEqual(workflow.run('APIRéponseRésumé23Item'), 'api+reponse+resume23+item')

    def test_case_015(self):
        self.assertEqual(workflow.run('APIRéponseRésumé23Item'), 'api+reponse+resume23+item')
        self.assertEqual(m.transliterate('ﬂower'), 'flower')
        self.assertEqual(m.transliterate('ﬂower'), 'ower')

if __name__ == '__main__':
    unittest.main()
