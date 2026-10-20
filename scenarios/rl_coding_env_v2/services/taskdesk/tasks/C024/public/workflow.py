"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    left = m.unique(map(tuple,data['entries']), key=lambda row: row[0])
    result = list(m.join(0, left, 0, map(tuple,data['lookup']), right_default=None))
    return json.loads(json.dumps(result))
