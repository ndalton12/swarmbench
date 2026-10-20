"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    tokens = m.replace(data, lambda a,b: a=='escape' and b==',', ['literal-comma'], window_size=2)
    result = list(m.split_at(tokens, lambda item:item==',', maxsplit=1))
    return json.loads(json.dumps(result))
