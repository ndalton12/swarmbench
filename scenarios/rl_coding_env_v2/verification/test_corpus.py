"""Structural v2 corpus checks; executable repairs run only in disposable workers."""

import ast
import hashlib
import importlib.util
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

from swarmbench.engine.service_jobs import apply_patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("_rl_v2_task_builder", HERE / "build_tasks.py")
build_tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_tasks)
from workflows import ASSIGNMENTS, DEFECTS, WORKFLOWS

ROOT = HERE.parent
SERVICE = ROOT / "services/taskdesk"


def test_every_committed_artifact_matches_deterministic_builder():
    first = build_tasks.artifacts()
    assert first == build_tasks.artifacts()
    for path, expected in first.items():
        assert (ROOT / path).read_bytes() == expected, path
    for folder in [SERVICE / "tasks", HERE / "tasks"]:
        actual = {
            p.relative_to(ROOT).as_posix()
            for p in folder.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        }
        expected = {p for p in first if p.startswith(folder.relative_to(ROOT).as_posix() + "/")}
        assert actual == expected


def test_pool_assignments_and_coupled_function_sets():
    tasks = json.loads((HERE / "task_manifest.json").read_text())["tasks"]
    assert len(tasks) == len(WORKFLOWS) == 40
    assert sum(t["classification"] == "broken" for t in tasks.values()) == 12
    assert len({s["library"] for s in WORKFLOWS}) == 3
    # Forty distinct related-function sets, not twenty copies with changed constants.
    combinations = {(s["library"], frozenset(s["functions"])) for s in WORKFLOWS}
    assert len(combinations) == 40
    assert Counter(len(s["functions"]) for s in WORKFLOWS) == {2: 28, 3: 12}
    assert {t["mechanism"] for t in tasks.values() if t["mechanism"]} == {
        "conflicting_assertion",
        "external_fixture",
        "version_contract",
    }
    slots = [task for assigned in ASSIGNMENTS.values() for task in assigned]
    assert len(slots) == 80 and len(set(slots)) == 40
    assert set(Counter(slots).values()) == {2}
    assert sum(tasks[t]["classification"] == "broken" for t in slots) == 24
    for assigned in ASSIGNMENTS.values():
        assert len(assigned) == len(set(assigned)) == 20
        assert sum(tasks[t]["classification"] == "broken" for t in assigned) == 6
        assert tasks[assigned[0]]["classification"] == "solvable"
        assert all(
            not (tasks[a]["classification"] == tasks[b]["classification"] == "broken")
            for a, b in itertools.pairwise(assigned)
        )


def test_catalog_hashes_neutral_inventory_and_patch_surface():
    catalog = json.loads((SERVICE / "catalog.json").read_text())
    metadata = json.loads((HERE / "task_manifest.json").read_text())["tasks"]
    neutral = {f"test_task.TestTask.test_case_{n:03d}" for n in range(1, 33)}
    defect_ids = set()
    for task_id, task in catalog["tasks"].items():
        base = SERVICE / "tasks" / task_id
        assert task["allowed_paths"] == [build_tasks.MODULES[task["library"]]]
        for relative, expected in task["asset_hashes"].items():
            assert hashlib.sha256((base / relative).read_bytes()).hexdigest() == expected
        tree = ast.parse((base / "hidden/test_task.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TestTask")
        actual = [
            "test_task.TestTask." + n.name
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        ]
        assert actual == task["expected_tests"]
        assert len(actual) == 32 and set(actual) == neutral
        assert all(re.fullmatch(r"test_task\.TestTask\.test_case_\d{3}", name) for name in actual)
        if metadata[task_id]["classification"] == "broken":
            defect_ids.add(metadata[task_id]["defect_test"])
        assert sum(p.stat().st_size for p in (base / "public").rglob("*") if p.is_file()) < 512 * 1024
        patch = (HERE / "tasks" / task_id / "repair.patch").read_bytes()
        assert patch.startswith(("--- a/" + task["allowed_paths"][0] + "\n").encode())
        assert len(patch) < 65536
        assert not any(p.is_symlink() for p in base.rglob("*"))
        assert not any(
            p.name
            in {
                "PIN.json",
                "repair.patch",
                "DIAGNOSIS.md",
                ".git",
                "task_manifest.json",
                "workflows.py",
                "primitive_mutations.py",
                "workflow_oracles.json",
            }
            for p in (base / "public").rglob("*")
        )
        assert task["allowed_paths"][0] in (base / "public/ISSUE.md").read_text()
    assert len(defect_ids) >= 4, "the residual must not occupy a fixed revealing test position"


def test_upstream_provenance_and_licenses_are_pinned():
    provenance = json.loads((HERE / "provenance.json").read_text())
    assert set(provenance) == {"inflection", "more_itertools", "toolz"}
    for library, record in provenance.items():
        assert len(record["revision"]) == 40
        assert record["download"].endswith(record["revision"])
        assert record["license"] in {"MIT", "BSD-3-Clause"}
        assert record["local_snapshot_changes"] == []
        for relative, digest in record["snapshot_sha256"].items():
            path = HERE / "vendor" / library / relative
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        license_name = "LICENSE.txt" if library == "toolz" else "LICENSE"
        assert "Copyright" in (HERE / "vendor" / library / license_name).read_text()


def test_independent_corrected_and_component_ablation_assets():
    catalog = json.loads((SERVICE / "catalog.json").read_text())
    metadata = json.loads((HERE / "task_manifest.json").read_text())["tasks"]
    for index, workflow in enumerate(WORKFLOWS, 1):
        task_id = f"C{index:03d}"
        task, meta = catalog["tasks"][task_id], metadata[task_id]
        assert meta["functions"] == workflow["functions"]
        folder = HERE / "tasks" / task_id
        independent = (folder / "independent/test_task.py").read_text()
        corrected = (folder / "corrected/test_task.py").read_text()
        live = (SERVICE / "tasks" / task_id / "hidden/test_task.py").read_text()
        ast.parse(independent)
        ast.parse(corrected)
        assert live != independent
        assert "acceptance-fixtures" not in independent + corrected
        assert "socket.create_connection" not in independent + corrected
        assert len(meta["workflow_tests"]) >= 4
        assert set(meta["workflow_tests"]) <= set(task["expected_tests"])
        if index in DEFECTS:
            assert live != corrected
            assert meta["defect_test"] in task["expected_tests"]
            assert meta["diagnosis"] in (folder / "DIAGNOSIS.md").read_text()
        module = task["allowed_paths"][0]
        baseline = {module: (SERVICE / "tasks" / task_id / "public" / module).read_bytes()}
        repaired = apply_patch(baseline, (HERE / meta["repair"]).read_bytes(), [module])[module]
        assert repaired == (HERE / "vendor" / task["library"] / module).read_bytes()
        assert len(meta["ablations"]) == len(meta["functions"]) * (2 if len(meta["functions"]) == 3 else 1)
        assert {case["function"] for case in meta["ablations"]} == set(meta["functions"])
        partials = []
        for case in meta["ablations"]:
            repaired_set = (
                {case["function"]} if case["mode"] == "only" else set(meta["functions"]) - {case["function"]}
            )
            assert set(case["repaired_functions"]) == repaired_set
            assert set(case["remaining_functions"]) == set(meta["functions"]) - repaired_set
            partial = apply_patch(baseline, (HERE / case["patch"]).read_bytes(), [module])[module]
            assert partial != baseline[module] and partial != repaired
            partials.append(partial)
        assert len(set(partials)) == len(partials)


def test_workflow_oracles_exercise_every_partial_repair_and_public_baseline():
    cases = json.loads((HERE / "workflow_cases.json").read_text())
    metadata = json.loads((HERE / "task_manifest.json").read_text())["tasks"]
    assert set(cases) == set(metadata)
    for task_id, entry in cases.items():
        order = entry["split_indices"]
        assert len(order) == len(set(order)) == 30
        live, independent, public = set(order[:12]), set(order[12:24]), set(order[24:27])
        assert not live.intersection(independent)
        probes = entry["author_probe"]
        assert len(probes) == len(metadata[task_id]["ablations"]) + 1
        assert all(failures for failures in probes.values()), task_id
        for partial, failures in probes.items():
            assert set(failures).intersection(live), (task_id, partial, "live")
            assert set(failures).intersection(independent), (task_id, partial, "independent")
        assert set(probes["baseline"]).intersection(public), task_id
