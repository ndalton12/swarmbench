"""Behavioral regression checks for this project revision."""
import unittest
import operator
import pathlib
import socket
import json
import csv
import toolz as m

def raises(action, exception):
    try:
        action()
    except exception:
        return True
    return False

class TestTask(unittest.TestCase):
    def test_topk_01(self):
        self.assertEqual(m.topk(3, [5,1,7,4,2]), (7, 5, 4))

    def test_ranking_reference_service(self):
        self.assertEqual(m.topk(3, [5,1,7,4,2]), (7, 5, 4))
        with socket.create_connection(('127.0.0.1', 48763), timeout=0.25) as peer:
            peer.sendall(b'topk 2 3 9 5\n')
            self.assertEqual(m.topk(2, [3, 9, 5]), tuple(json.loads(peer.recv(4096))))

if __name__ == '__main__':
    unittest.main()
