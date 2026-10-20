"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    label = 'position ' + m.ordinalize(data)
    result = {'label': label, 'route': m.parameterize(label, separator='.')}
    return json.loads(json.dumps(result))
