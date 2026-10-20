"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    projected = list(m.pluck(['group','value'], data['rows'], default=0))
    result = m.get([data['index']], projected)
    return json.loads(json.dumps(result))
