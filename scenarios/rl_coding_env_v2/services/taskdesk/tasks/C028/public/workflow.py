"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    changes = m.difference(data['readings'])
    result = list(m.windowed(changes, data['width'], step=data['step'], fillvalue=0))
    return json.loads(json.dumps(result))
