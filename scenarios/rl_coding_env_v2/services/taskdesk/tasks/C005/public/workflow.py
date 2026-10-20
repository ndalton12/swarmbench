"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    label = m.humanize(m.transliterate(data))
    result = {'label': label, 'slug': m.parameterize(label, separator='+')}
    return json.loads(json.dumps(result))
