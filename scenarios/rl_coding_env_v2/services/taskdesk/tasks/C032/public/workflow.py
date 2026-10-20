"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    items = list(m.padded(data['items'], 0, data['minimum']))
    blocks = m.divide(data['parts'], items)
    result = [None]*data['parts']
    for index in data['order']:
        result[index] = list(blocks[index])
    return json.loads(json.dumps(result))
