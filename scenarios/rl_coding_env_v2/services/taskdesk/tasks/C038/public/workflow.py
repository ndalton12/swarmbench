"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    tokens = m.replace(data['items'], lambda a,b:a=='private' and b=='value', ['redacted'], count=data['limit'], window_size=2)
    result = list(m.windowed(tokens, data['width'], step=data['step'], fillvalue='pad'))
    return json.loads(json.dumps(result))
