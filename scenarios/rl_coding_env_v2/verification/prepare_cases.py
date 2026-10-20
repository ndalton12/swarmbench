"""Authoring-only trusted upstream oracle. Run inside an offline container."""

import ast
import importlib
import json
import pathlib
import random
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from mutations import mutate, workflow_source
from workflows import WORKFLOWS

MODULES = {
    "inflection": "inflection/__init__.py",
    "toolz": "toolz/itertoolz.py",
    "more_itertools": "more_itertools/more.py",
}
for library in MODULES:
    sys.path.insert(0, str(HERE / "vendor" / library))


def capture(run, data):
    try:
        return {"value": run(data)}
    except Exception as error:
        return {"raises": type(error).__name__}


output = {}
for index, spec in enumerate(WORKFLOWS, 1):
    library = spec["library"]
    package = importlib.import_module(library)
    module = importlib.import_module(
        library if library == "inflection" else library + (".itertoolz" if library == "toolz" else ".more")
    )
    original = (HERE / "vendor" / library / MODULES[library]).read_text()
    saved = {function: getattr(module, function) for function in spec["functions"]}
    env = {}
    exec(workflow_source(spec), env)  # noqa: S102 - trusted author recipe, offline container only
    cases = [dict(input=data, **capture(env["run"], data)) for data in spec["inputs"]]
    failures = {}
    alternatives = {}
    subsets = [(), *[(f,) for f in spec["functions"]]]
    if len(spec["functions"]) > 2:
        subsets += [tuple(f for f in spec["functions"] if f != omitted) for omitted in spec["functions"]]
    for repaired in subsets:
        source = mutate(original, spec, repaired)
        tree = ast.parse(source)
        for function in spec["functions"]:
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            exec(  # noqa: S102 - trusted author recipe, offline container only
                compile(ast.Module(body=[node], type_ignores=[]), "<trusted author recipe>", "exec"),
                module.__dict__,
            )
            setattr(package, function, getattr(module, function))
        actual = [capture(env["run"], case["input"]) for case in cases]
        bad = [
            i
            for i, (case, value) in enumerate(zip(cases, actual))
            if {k: v for k, v in case.items() if k != "input"} != value
        ]
        key = ",".join(repaired) or "baseline"
        failures[key] = bad
        alternatives[key] = actual
        for function, value in saved.items():
            setattr(module, function, value)
            setattr(package, function, value)
    if not all(failures.values()):
        raise ValueError(("INEFFECTIVE", index, spec["functions"], failures))
    for seed in range(index * 1000, index * 1000 + 1000):
        indices = list(range(30))
        random.Random(seed).shuffle(indices)
        if all(
            set(bad).intersection(indices[:12]) and set(bad).intersection(indices[12:24])
            for bad in failures.values()
        ) and set(failures["baseline"]).intersection(indices[24:27]):
            break
    else:
        raise ValueError(("NO_BALANCED_SPLIT", index, failures))
    output[f"C{index:03d}"] = {
        "live": [cases[i] for i in indices[:12]],
        "independent": [cases[i] for i in indices[12:24]],
        "public": [cases[i] for i in indices[24:27]],
        "additional": [cases[i] for i in indices[27:]],
        "split_indices": indices,
        "split_seed": seed,
        "author_probe": failures,
        "alternatives": alternatives,
        "all_cases": cases,
    }
print(json.dumps(output, indent=2, sort_keys=True))
