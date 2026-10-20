"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    fields = m.always_iterable(data['fields'])
    result = list(m.replace(fields, lambda field:field==data['target'], ['redacted'], count=data['limit']))
    return json.loads(json.dumps(result))
