"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    key = m.underscore(m.transliterate(data))
    result = m.parameterize(key.replace('_', ' '), separator='+')
    return json.loads(json.dumps(result))
