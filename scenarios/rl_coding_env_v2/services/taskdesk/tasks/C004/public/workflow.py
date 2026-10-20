"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    section = m.dasherize(data['section'])
    result = m.parameterize(section + ' ' + m.ordinalize(data['rank']), separator='+')
    return json.loads(json.dumps(result))
