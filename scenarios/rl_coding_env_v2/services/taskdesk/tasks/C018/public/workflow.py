"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    frames = m.partition_all(data['size'], data['items'])
    result = list(m.interpose(['boundary'], frames))
    return json.loads(json.dumps(result))
