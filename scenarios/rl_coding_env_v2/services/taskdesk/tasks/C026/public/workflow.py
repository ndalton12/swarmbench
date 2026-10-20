"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    preview, replay = m.peekn(data['preview'], iter(data['items']))
    received = list(replay)
    result = {'preview': preview, 'received': len(received), 'recent': m.tail(data['count'], iter(received))}
    return json.loads(json.dumps(result))
