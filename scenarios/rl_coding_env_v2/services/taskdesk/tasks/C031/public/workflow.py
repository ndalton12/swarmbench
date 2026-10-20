"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    segments = m.split_after(data['items'], lambda item:item=='commit', maxsplit=1)
    result = [list(m.chunked(segment, data['size'], strict=True)) for segment in segments]
    return json.loads(json.dumps(result))
