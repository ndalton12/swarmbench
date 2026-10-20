"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    parts = [m.pluralize(part) for part in data]
    result = m.camelize(m.underscore('_'.join(parts)), False)
    return json.loads(json.dumps(result))
