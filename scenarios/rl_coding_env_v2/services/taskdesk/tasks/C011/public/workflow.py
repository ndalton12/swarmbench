"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    raw = '_'.join(m.pluralize(part) for part in data)
    result = m.humanize(m.underscore(raw))
    return json.loads(json.dumps(result))
