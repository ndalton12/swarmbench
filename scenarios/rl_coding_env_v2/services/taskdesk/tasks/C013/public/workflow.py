"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    projected = m.pluck(['group', 'value'], data, default=0)
    result = list(m.unique(projected, key=lambda row: row[0].lower()))
    return json.loads(json.dumps(result))
