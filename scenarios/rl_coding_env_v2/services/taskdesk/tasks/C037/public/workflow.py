"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    changes = list(m.difference(data['items']))
    result = {'changes': changes, 'ordered': m.is_sorted(changes, reverse=True, strict=data['strict'])}
    return json.loads(json.dumps(result))
