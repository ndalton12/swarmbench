"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    pairs = list(m.join(0, map(tuple,data['entries']), 0, map(tuple,data['weights']), left_default=None, right_default=None))
    key = lambda pair: pair[0][0] if pair[0] is not None else pair[1][0]
    amount = lambda pair: (pair[0][1] if pair[0] is not None else 0) * (pair[1][1] if pair[1] is not None else 1)
    totals = m.reduceby(key, lambda total,pair: total+amount(pair), pairs, 0)
    members = m.reduceby(key, lambda group,pair: (group.append(pair) or group), pairs, list)
    result = {'totals': totals, 'members': members}
    return json.loads(json.dumps(result))
