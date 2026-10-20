"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    blocks = m.divide(data['parts'], data['items'])
    result = [None]*data['parts']
    for index in data['order']:
        result[index] = list(m.windowed(blocks[index], data['width'], step=data['step'], fillvalue=0))
    return json.loads(json.dumps(result))
