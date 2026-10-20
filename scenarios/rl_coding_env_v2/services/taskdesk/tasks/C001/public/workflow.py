"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    canonical = m.underscore(data)
    result = {'key': m.camelize(canonical, False), 'label': m.humanize(canonical)}
    return json.loads(json.dumps(result))
