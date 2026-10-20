"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    result = m.titleize(m.transliterate(data))
    return json.loads(json.dumps(result))
