"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    channels = m.distribute(data['channels'], iter(data['items']))
    result = [None] * data['channels']
    for index in data['order']:
        result[index] = list(m.chunked(channels[index], data['size'], strict=True))
    return json.loads(json.dumps(result))
