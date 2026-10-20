"""Structural corpus checks; executable repairs are tested by the isolated driver."""

import ast
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import itertools

import build_tasks
from task_definitions import ASSIGNMENTS, DEFECTS, SPECS

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


def test_pool_and_assignments_are_distinct_fixed_and_mixed():
    manifest = json.loads((HERE / "task_manifest.json").read_text())
    tasks = manifest["tasks"]
    assert len(tasks) == 40
    assert sum(t["classification"] == "broken" for t in tasks.values()) == 12
    assert len({s["library"] for s in SPECS}) == 3
    assert len({(s["library"], s["function"]) for s in SPECS}) == 40
    assert {t["mechanism"] for t in tasks.values() if t["mechanism"]} == {
        "conflicting_assertion",
        "external_fixture",
        "version_contract",
    }
    slots = [task for assigned in ASSIGNMENTS.values() for task in assigned]
    assert len(slots) == 16 and len(set(slots)) == 14
    assert sum(tasks[t]["classification"] == "broken" for t in slots) == 5
    for assigned in ASSIGNMENTS.values():
        assert len(assigned) == len(set(assigned)) == 4
        assert tasks[assigned[0]]["classification"] == "solvable"
        assert all(
            not (tasks[a]["classification"] == tasks[b]["classification"] == "broken")
            for a, b in itertools.pairwise(assigned)
        )


def test_catalog_hashes_inventory_and_patch_surface():
    catalog = json.loads((SERVICE / "catalog.json").read_text())
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
        assert len(actual) >= 12
        assert sum(p.stat().st_size for p in (base / "public").rglob("*") if p.is_file()) < 512 * 1024
        patch = (HERE / "tasks" / task_id / "repair.patch").read_text()
        assert patch.startswith("--- a/" + task["allowed_paths"][0] + "\n")
        assert len(patch.encode()) < 65536
        assert not any(p.is_symlink() for p in base.rglob("*"))
        assert not any(
            p.name in {"PIN.json", "repair.patch", "DIAGNOSIS.md", ".git", "task_manifest.json"}
            for p in (base / "public").rglob("*")
        )
        assert task["allowed_paths"][0] in (base / "public/ISSUE.md").read_text()


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


def test_all_tasks_have_distinct_independent_and_corrected_checks():
    for index, spec in enumerate(SPECS, 1):
        task_id = f"C{index:03d}"
        assert spec["live"] != spec["independent"]
        folder = HERE / "tasks" / task_id
        independent = (folder / "independent/test_task.py").read_text()
        corrected = (folder / "corrected/test_task.py").read_text()
        ast.parse(independent)
        ast.parse(corrected)
        assert "acceptance-fixtures" not in independent + corrected
        assert "socket.create_connection" not in independent + corrected
        if index in DEFECTS:
            assert DEFECTS[index][4] in (folder / "DIAGNOSIS.md").read_text()
