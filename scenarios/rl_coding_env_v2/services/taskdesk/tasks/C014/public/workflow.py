"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    deltas = (right-left for left,right in m.sliding_window(2, data['readings']))
    result = list(m.accumulate(operator.sub, deltas, data['opening']))
    return json.loads(json.dumps(result))
