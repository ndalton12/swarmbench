"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    projected = list(m.pluck(['group','value'], data, default=0))
    totals = m.reduceby(0, lambda total,row: total+row[1], projected, 0)
    members = m.reduceby(0, lambda group,row: (group.append(row) or group), projected, list)
    result = {'totals': totals, 'members': members}
    return json.loads(json.dumps(result))
