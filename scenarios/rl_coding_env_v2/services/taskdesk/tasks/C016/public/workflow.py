"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    result = m.tail(data['count'], m.interleave(iter(stream) for stream in data['streams']))
    return json.loads(json.dumps(result))
