"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    streams = m.distribute(data['channels'], iter(data['items']))
    result = [None]*data['channels']
    for index in data['order']:
        values = list(streams[index])
        result[index] = {'items': values, 'ordered': m.is_sorted(values, reverse=True, strict=data['strict'])}
    return json.loads(json.dumps(result))
