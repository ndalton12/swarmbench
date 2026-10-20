"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    canonical = m.underscore(data)
    result = {'heading': m.titleize(data), 'caption': m.humanize(canonical)}
    return json.loads(json.dumps(result))
