"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    merged = list(m.interleave(iter(stream) for stream in data['streams']))
    result = list(m.partition_all(data['size'], merged))
    return json.loads(json.dumps(result))
