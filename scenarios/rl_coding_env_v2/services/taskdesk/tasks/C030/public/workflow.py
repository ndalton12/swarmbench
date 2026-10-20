"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import more_itertools as m

def run(data):
    ranges = [list(group) for group in m.consecutive_groups(data['items'], ordering=int)]
    result = list(m.split_before(ranges, lambda group:int(group[0])>=data['threshold'], maxsplit=1))
    return json.loads(json.dumps(result))
