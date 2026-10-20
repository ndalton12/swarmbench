"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    counts = m.frequencies(data['items'])
    result = m.topk(data['count'], counts.items(), key=lambda row: (row[1], row[0]))
    return json.loads(json.dumps(result))
