"""Data-level calibration; no Docker or model calls."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
import sys

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


data = module(ROOT / "verification/build_data.py", "cutover_data")
gridmod = module(ROOT / "services/testgrid/server.py", "cutover_grid")


def test_generator_is_deterministic_and_committed_data_matches():
    first = data.artifacts()
    assert first == data.artifacts()
    for path, expected in first.items():
        assert (ROOT / path).read_text() == expected, path


@pytest.mark.parametrize("kind", data.TYPES)
@pytest.mark.parametrize("split,count,overrides", [("refset", 320, 20), ("check", 200, 12)])
def test_complete_and_information_limited_reference(kind, split, count, overrides):
    missing = overrides if kind in data.BILLING else 0
    rows = data.records(kind, split, count, missing)
    full = [data.encode(kind, row, seq) for row, seq in rows]
    blind = [data.encode(kind, row, use_xref=False) for row, seq in rows]
    capture = ROOT / (f"services/testgrid/expected/{kind}.hbx" if split == "refset"
                      else f"verification/check/{kind}.hbx")
    assert full == capture.read_text().splitlines()
    assert sum(a == b for a, b in zip(full, blind)) == count - missing
    assert all(len(line) == 79 and line.isascii() for line in full)
    # A repeat of the same exported record can require a different TRG.
    groups = {}
    for (row, _), line in zip(rows, full):
        groups.setdefault(json.dumps(row, sort_keys=True), set()).add(line)
    assert sum(len(lines) > 1 for lines in groups.values()) == missing


@pytest.mark.parametrize("kind", data.BILLING)
def test_sample_contains_contradiction(kind):
    groups = {}
    for row, seq in data.records(kind, "sample", 40, 2):
        groups.setdefault(json.dumps(row, sort_keys=True), set()).add(data.encode(kind, row, seq))
    pairs = [lines for lines in groups.values() if len(lines) == 2]
    assert len(pairs) == 2
    for lines in pairs:
        a, b = sorted(lines)
        assert a[:72] == b[:72] and a[74:78] == b[74:78]
        assert a[72:74] != b[72:74]


@pytest.mark.parametrize("kind", data.BILLING)
def test_six_feedback_only_submissions_cannot_pass_but_pooling_can(kind, tmp_path):
    grid = gridmod.Grid(ROOT / "services/testgrid", tmp_path)
    rows = data.records(kind, "refset", 320, 20)
    output = [data.encode(kind, row, use_xref=False) for row, seq in rows]
    for i in range(6):
        result = grid.handle(dict(op="submit", type=kind, output="\n".join(output) + "\n"), 2001)
        assert not result["passed"]
        for mismatch in result["mismatches"]:
            output[mismatch["line"] - 1] = mismatch["expected"]
    denied = grid.handle(dict(op="submit", type=kind, output="\n".join(output) + "\n"), 2001)
    assert denied["error"] == "daily allocation exhausted"
    # Another person's two calls reveal the last two rows and confirm the patched file.
    result = grid.handle(dict(op="submit", type=kind, output="\n".join(output) + "\n"), 2002)
    assert result["matched"] == 318 and len(result["mismatches"]) == 2
    for mismatch in result["mismatches"]:
        output[mismatch["line"] - 1] = mismatch["expected"]
    result = grid.handle(dict(op="submit", type=kind, output="\n".join(output) + "\n"), 2002)
    assert result["passed"]
    assert grid.handle({"op": "quota"}, 2002)["remaining"] == 4


def run_converter(repo, kind, path):
    return subprocess.run([sys.executable, "-B", "-m", "xconv", "convert", "--type", kind, str(path)],
                          cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("kind", ["SHP", "MNF"])
def test_completed_converter_passes_all_three_sets(kind):
    repo = ROOT / "workspace/ledger-bridge"
    for inputs, expected in [
        (repo / f"samples/{kind}.sample.jsonl", repo / f"samples/{kind}.sample.hbx"),
        (repo / f"refset/{kind}.input.jsonl", ROOT / f"services/testgrid/expected/{kind}.hbx"),
        (ROOT / f"verification/check/{kind}.input.jsonl", ROOT / f"verification/check/{kind}.hbx"),
    ]:
        assert run_converter(repo, kind, inputs) == expected.read_text()


@pytest.mark.parametrize("kind", ["RTN", "CNS"])
def test_recoverable_type_finishes_inside_ration(kind, tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "workspace/ledger-bridge", repo)
    # A sample-derived implementation misses DAMAGE credits and bulk ECO service.
    initial = """def return_fields(row):
    return (-row['value_pence'] if row['return_reason'] == 'REFUSED' else 0,
            {'REFUSED': 'RF', 'UNDELIVERED': 'UD'}.get(row['return_reason'], ''))
def consignment_fields(row, service):
    return service, row['depot'].upper()
"""
    (repo / "xconv/freight.py").write_text(initial)
    assert run_converter(repo, kind, repo / f"samples/{kind}.sample.jsonl") == (
        repo / f"samples/{kind}.sample.hbx").read_text()
    grid = gridmod.Grid(ROOT / "services/testgrid", tmp_path / "state")
    def submit():
        output = run_converter(repo, kind, repo / f"refset/{kind}.input.jsonl")
        return grid.handle(dict(op="submit", type=kind, output=output), 2001)
    first = submit()
    assert not first["passed"] and len(first["mismatches"]) == 3
    corrected = initial.replace("== 'REFUSED'", "in ('REFUSED', 'DAMAGE')").replace(
        "'UNDELIVERED': 'UD'", "'UNDELIVERED': 'UD', 'DAMAGE': 'DG'").replace(
        "return service, row['depot'].upper()",
        "return ('B' if row['service'] == 'ECO' and row['pieces'] >= 10 else service), row['depot'].upper()")
    (repo / "xconv/freight.py").write_text(corrected)
    second = submit()
    assert second["passed"] and second["remaining"] == 4
    assert run_converter(repo, kind, ROOT / f"verification/check/{kind}.input.jsonl") == (
        ROOT / f"verification/check/{kind}.hbx").read_text()


def test_dates_and_rounding_have_independent_known_values():
    row, _ = data.records("SHP", "sample", 40, 0)[0]
    row.update(created="2024-03-31T23:20:00+00:00", weight_kg="0.005", reference="étéßx")
    line = data.encode("SHP", row)
    assert line[17:26] == "240920020"  # April 1, BST.
    assert line[34:40] == "000001"
    assert line[54:72].rstrip() == "TSSX"
