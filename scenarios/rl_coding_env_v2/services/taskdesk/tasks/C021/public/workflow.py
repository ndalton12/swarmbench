"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    preview, replay = m.peekn(data['preview'], iter(data['items']))
    result = {'preview': preview, 'windows': list(m.sliding_window(data['width'], replay))}
    return json.loads(json.dumps(result))
