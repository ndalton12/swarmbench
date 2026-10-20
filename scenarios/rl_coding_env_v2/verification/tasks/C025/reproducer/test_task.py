"""Integration and API regression checks."""
import unittest
import operator
import pathlib
import socket
import json
import workflow
import toolz as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_case_001(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A5', 'B5', 'A5', 'C5', 'A5', 'B5', 'D5']}), [['A5', 3], ['B5', 2], ['D5', 1]])

    def test_case_021(self):
        self.assertEqual(workflow.run({'count': 3, 'items': ['A5', 'B5', 'A5', 'C5', 'A5', 'B5', 'D5']}), [['A5', 3], ['B5', 2], ['D5', 1]])
        with socket.create_connection(('127.0.0.1', 48763), timeout=0.25) as peer:
            peer.sendall(b'digest snapshot\n')
            snapshot = json.loads(peer.recv(4096))
        self.assertEqual(workflow.run({'count': 3, 'items': ['A5', 'B5', 'A5', 'C5', 'A5', 'B5', 'D5']}), snapshot['expected'])

if __name__ == '__main__':
    unittest.main()
