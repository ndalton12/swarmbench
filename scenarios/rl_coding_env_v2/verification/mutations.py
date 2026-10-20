"""Faulty refactors used by related workflows; author-only."""

import ast
import textwrap

from workflows import BY_FUNCTION

BODIES = {
    ("toolz", "unique"): """
seen = set()
previous = object()
for item in seq:
    marker = item if key is None else key(item)
    if marker == previous:
        continue
    previous = marker
    if key is None:
        if marker in seen:
            continue
        seen.add(marker)
    else:
        seen.add(marker)
    yield item
""",
    ("toolz", "interleave"): """
active = list(map(iter, seqs))
while active:
    for position, stream in enumerate(active):
        try:
            value = next(stream)
        except StopIteration:
            del active[position]
            continue
        yield value
""",
    ("toolz", "reduceby"): """
missing = init == no_default
initial = None if missing else (init() if callable(init) else init)
if not callable(key):
    key = getter(key)
result = {}
for item in seq:
    group = key(item)
    if group not in result:
        result[group] = item if missing else initial
        continue
    result[group] = binop(result[group], item)
return result
""",
    ("toolz", "partition_all"): """
if n < 1:
    raise ValueError('partition size must be positive')
buffer = []
for item in seq:
    buffer.append(item)
    if len(buffer) == n:
        yield tuple(buffer)
        buffer.clear()
if buffer:
    yield tuple(buffer[:-1])
""",
    ("toolz", "peekn"): """
source = iter(seq)
preview = []
for index in range(n):
    try:
        preview.append(next(source))
    except StopIteration:
        saved = tuple(preview)
        return saved, iter(saved)
return tuple(preview), source
""",
    ("more_itertools", "distribute"): """
if n < 1:
    raise ValueError('n must be at least 1')
source = iter(iterable)
children = [source] * n
return [islice(child, index, None, n) for index, child in enumerate(children)]
""",
    ("more_itertools", "divide"): """
if n < 1:
    raise ValueError('n must be at least 1')
try:
    length = len(iterable)
except TypeError:
    iterable = tuple(iterable)
    length = len(iterable)
width, extra = divmod(length, n)
source = iter(iterable)
return [islice(source, width + (index < extra)) for index in range(n)]
""",
}


def mutate_function(source, library, function):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == function)
    lines = source.splitlines(keepends=True)
    if (library, function) in BODIES:
        begin = (
            node.body[1].lineno - 1
            if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
            else node.body[0].lineno - 1
        )
        replacement = textwrap.indent(textwrap.dedent(BODIES[library, function]).strip() + "\n", "    ")
        result = "".join(lines[:begin]) + replacement + "".join(lines[node.end_lineno :])
    else:
        spec = BY_FUNCTION[library, function]
        segment = "".join(lines[node.lineno - 1 : node.end_lineno])
        assert spec["old"] in segment, (library, function)
        segment = segment.replace(spec["old"], spec["new"], 1)
        for old, new in spec.get("extra_mutations", []):
            assert old in segment, (library, function, old)
            segment = segment.replace(old, new, 1)
        if library == "inflection" and function == "pluralize":
            segment = segment.replace(
                "for rule, replacement in PLURALS:", "for rule, replacement in reversed(PLURALS):"
            )
        if library == "toolz" and function == "join":
            segment = segment.replace("seen(key)", "seen(item)")
        if library == "toolz" and function == "accumulate":
            segment = segment.replace("result = initial", "result = initial\n        next(seq, None)")
        result = "".join(lines[: node.lineno - 1]) + segment + "".join(lines[node.end_lineno :])
    ast.parse(result)
    return result


def mutate(source, spec, repaired=()):
    for function in spec["functions"]:
        if function not in repaired:
            source = mutate_function(source, spec["library"], function)
    return source


def workflow_source(spec):
    return (
        '"""Example integration from the issue report. Run local tests to reproduce it."""\n'
        "import json\nimport operator\nimport " + spec["library"] + " as m\n\n"
        "def run(data):\n"
        + textwrap.indent(spec["body"].strip(), "    ")
        + "\n    return json.loads(json.dumps(result))\n"
    )
