"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import inflection as m

def run(data):
    table = m.tableize(data)
    result = {'table': table, 'collection': m.camelize(table, False)}
    return json.loads(json.dumps(result))
