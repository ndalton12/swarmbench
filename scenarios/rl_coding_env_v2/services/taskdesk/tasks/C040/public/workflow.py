"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    features = m.always_iterable(data['features'])
    result = list(m.distinct_combinations(features, data['size']))
    return json.loads(json.dumps(result))
