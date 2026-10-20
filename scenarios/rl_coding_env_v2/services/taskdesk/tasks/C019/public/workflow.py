"""Example integration from the issue report. Run local tests to reproduce it."""
import json
import operator
import toolz as m

def run(data):
    counts = m.frequencies(word.lower() for word in data)
    annotated = [(word, counts[word.lower()]) for word in data]
    result = list(m.unique(annotated, key=lambda row: row[0].lower()))
    return json.loads(json.dumps(result))
