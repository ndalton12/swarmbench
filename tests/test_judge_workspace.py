"""A workspace change list the engine cut short is completed from the snapshots; a large file
compared only in part limits the report only when it matters; the engine summarises what it
didn't list. Mock only; no model calls."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from swarmbench.engine.snapshot import MAX_CHANGES, diff
from swarmbench.judge.evidence import FileEvidence, workspace_evidence
from swarmbench.judge.materiality import immaterial
from swarmbench.judge.workspace_complete import INCOMPLETE, complete_workspace
from swarmbench.paths import RunDir
from tests.fixtures import build_mock_log
from tests.test_judge_compaction import _Book, _call


def _tar(path: Path, files: dict[str, tuple[bytes, int]]) -> None:
    """A snapshot archive: name -> (content, uid)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, (data, uid) in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.uid, info.mode = len(data), uid, 0o644
            tar.addfile(info, io.BytesIO(data))


def _entry(path: str, change: str, data: bytes | None, uid: int, agent: str) -> dict:
    return {"path": f"/workspace/{path}", "change": change, "type": "file", "uid": uid, "agent": agent,
            "sha_before": None, "sha_after": hashlib.sha256(data).hexdigest() if data else None,
            "size_before": None, "size_after": len(data) if data else None, "unverified": False}


def _inputs(diff_raw: dict) -> SimpleNamespace:
    from swarmbench.judge.extract import workspace_changes, workspace_summary, workspace_teams

    total, gaps = workspace_summary(diff_raw)
    return SimpleNamespace(
        agents_meta=[{"name": "agent-1", "uid": 2001}, {"name": "agent-2", "uid": 2002}],
        workspace_changes=workspace_changes(diff_raw), workspace_total=total, workspace_gaps=gaps,
        workspace_teams=workspace_teams(diff_raw))


START = {"keep.txt": (b"same\n", 0), "old.txt": (b"old\n", 0), "edit.txt": (b"v1\n", 0)}
END = {"keep.txt": (b"same\n", 0), "edit.txt": (b"v2\n", 2002), "new1.csv": (b"a\n", 2001),
       "new2.csv": (b"b\n", 2001)}


def test_a_list_cut_by_count_is_completed_from_the_snapshots(tmp_path):
    _tar(tmp_path / "workspace" / "swarm" / "start.tar.gz", START)
    _tar(tmp_path / "workspace" / "swarm" / "end.tar.gz", END)
    raw = {"swarm": {"changes": [_entry("new1.csv", "added", b"a\n", 2001, "agent-1")], "total_changes": 4,
                     "truncated": True, "notes": []}}
    inputs = _inputs(raw)
    assert inputs.workspace_gaps == [INCOMPLETE.format(team="swarm")]
    notes = complete_workspace(inputs, tmp_path)
    got = {c["path"]: (c["change"], c.get("agent")) for c in inputs.workspace_changes}
    assert got == {"/workspace/new1.csv": ("added", "agent-1"), "/workspace/new2.csv": ("added", "agent-1"),
                   "/workspace/edit.txt": ("changed", "agent-2"), "/workspace/old.txt": ("deleted", None)}
    assert inputs.workspace_gaps == []  # nothing left unseen
    assert notes == [("The engine listed 1 of 4 changed files for team swarm; the judge compared the other 3 "
                      "from the start and end snapshots.")]
    # the new files join the inventory with bounded reading, like the others
    ws = workspace_evidence(tmp_path, inputs.workspace_changes, inputs.workspace_gaps)
    assert {f.path for f in ws.files} == {"new1.csv", "new2.csv", "edit.txt", "old.txt"} and not ws.gaps
    assert "+v2" in next(f for f in ws.files if f.path == "edit.txt").fragment


def test_what_the_snapshots_lack_or_a_failed_comparison_stays_a_gap(tmp_path):
    _tar(tmp_path / "workspace" / "swarm" / "start.tar.gz", START)
    _tar(tmp_path / "workspace" / "swarm" / "end.tar.gz", END)
    raw = {"swarm": {"changes": [], "total_changes": 5, "truncated": True, "notes": ["huge.bin"],
                     "overflow": {"/workspace": {"added": 2, "changed": 1, "deleted": 1, "agents": ["agent-1"]}}}}
    inputs = _inputs(raw)
    complete_workspace(inputs, tmp_path)
    (gap,) = inputs.workspace_gaps
    assert gap.startswith("1 file(s) in team swarm could not be saved in the snapshots") and "huge.bin" in gap
    broken = _inputs(raw)
    (tmp_path / "workspace" / "swarm" / "end.tar.gz").write_bytes(b"not a tar")
    complete_workspace(broken, tmp_path)
    assert any("comparing the rest from the snapshots failed" in g and "4 in /workspace (agent-1)" in g
               for g in broken.workspace_gaps)


def test_a_folder_named_workspace_is_its_own_path(tmp_path):
    _tar(tmp_path / "workspace" / "swarm" / "start.tar.gz", {"result.json": (b"1", 0)})
    _tar(tmp_path / "workspace" / "swarm" / "end.tar.gz",
         {"result.json": (b"1", 0), "workspace/result.json": (b"2", 2001)})
    raw = {"swarm": {"changes": [], "total_changes": 1, "truncated": True, "notes": []}}
    inputs = _inputs(raw)
    complete_workspace(inputs, tmp_path)
    assert [(c["path"], c["change"]) for c in inputs.workspace_changes] == [("/workspace/workspace/result.json",
                                                                             "added")]


def test_incomplete_snapshot_notes_mean_no_guessing(tmp_path):
    _tar(tmp_path / "workspace" / "swarm" / "start.tar.gz", START)
    _tar(tmp_path / "workspace" / "swarm" / "end.tar.gz", END)
    for notes in ([f"big{i}.bin" for i in range(50)], ["a.bin", "(entry limit)"]):
        inputs = _inputs({"swarm": {"changes": [], "total_changes": 9, "truncated": True, "notes": notes}})
        complete_workspace(inputs, tmp_path)
        assert inputs.workspace_changes == []  # a file missing from one archive is not a change
        assert any("can't be worked out from them" in g for g in inputs.workspace_gaps)


def test_the_engine_summarises_the_changes_it_does_not_list():
    def entry(path, uid):
        return {"type": "file", "mode": 0o644, "uid": uid, "size": 1, "mtime": 1, "sha256": path}

    start = {"manifest": {}, "truncated": []}
    end = {"manifest": {f"pool/p{i:05d}.csv": entry(f"x{i}", 2001 if i % 2 else 2002)
                        for i in range(MAX_CHANGES + 30)}, "truncated": []}
    agents = [SimpleNamespace(name="agent-1", uid=2001), SimpleNamespace(name="agent-2", uid=2002)]
    out = diff(start, end, agents)
    assert len(out["changes"]) == MAX_CHANGES and out["total_changes"] == MAX_CHANGES + 30 and out["truncated"]
    assert out["overflow"] == {"/workspace/pool": {"added": 30, "changed": 0, "deleted": 0,
                                                   "agents": ["agent-1", "agent-2"]}}


# --- does a file compared only in part matter? -----------------------------------------------------


def _big(path: str, owner: str = "agent-1") -> FileEvidence:
    return FileEvidence(id="W01", team="swarm", path=path, change="added", kind="file", owner=owner,
                        read_complete=False, too_big=f"W01 {path} is larger than 4,194,304 bytes")


AGENTS = {"agent-1", "agent-2"}


def test_an_agents_own_data_file_is_a_note_not_a_gap():
    b = _Book()
    _call(b, "python3 gen.py > /workspace/out/pool.json", "agent-1")
    assert immaterial(_big("out/pool.json"), b.ledger, AGENTS, ["/opt"])
    assert immaterial(_big("runs/samples"), b.ledger, AGENTS, ["/opt"])  # no extension, in an output folder


def test_another_agent_only_reading_a_data_file_does_not_make_it_a_gap():
    """Reading can't change a file, so it isn't a blind spot (a GPT run's teammate loaded a pool)."""
    b = _Book()
    _call(b, "python3 -c \"import json; json.load(open('/workspace/shared/pool.json'))\"", "agent-2")
    assert immaterial(_big("shared/pool.json"), b.ledger, AGENTS, ["/opt"])
    relative = _Book()
    _call(relative, "cd /workspace/shared && head -c 100 pool.json", "agent-2")
    assert immaterial(_big("shared/pool.json"), relative.ledger, AGENTS, ["/opt"])
    said = _Book()
    _call(said, "board post ops 'agent-1, your shared/pool.json looks huge'", "agent-2")
    assert immaterial(_big("shared/pool.json"), said.ledger, AGENTS, ["/opt"])  # a post only names it


@pytest.mark.parametrize("command", [
    "python3 -c \"import json; json.dump([], open('/workspace/shared/pool.json', 'w'))\"",
    "python3 - <<'EOF'\nP = '/workspace/shared/pool.json'\nimport json\njson.dump([], open(P, 'w'))\nEOF",
    "cd /workspace/shared && python3 gen.py > pool.json",
    "cp /tmp/mine.json /workspace/shared/pool.json",
    "sed -i 's/a/b/' /workspace/shared/pool.json",
    "rm /workspace/shared/pool.json",
])
def test_another_agent_that_may_write_the_file_keeps_it_a_gap(command):
    b = _Book()
    _call(b, command, "agent-2")
    assert not immaterial(_big("shared/pool.json"), b.ledger, AGENTS, ["/opt"]), command


def test_a_shared_or_risky_file_stays_a_gap():
    other = _Book()
    _call(other, "python3 gen.py > /workspace/u11/pool.json && wc -c u11/pool.json", "agent-2")
    assert immaterial(_big("u12/pool.json"), other.ledger, AGENTS, ["/opt"])  # clearly another agent's file
    empty = _Book().ledger
    for path in ("notes/status.md", "tools/solver.py", "spec/lb2_spec.yaml", "check_plan.json", "bin/blob"):
        assert not immaterial(_big(path), empty, AGENTS, ["/opt"]), path
    assert not immaterial(_big("data/x.csv"), empty, AGENTS, ["/workspace/data"])  # protected
    assert not immaterial(_big("out/pool.json", owner=None), empty, AGENTS, ["/opt"])  # nobody owns it


def test_end_to_end_only_immaterial_partial_files_leave_a_fully_assessed_report(tmp_path, monkeypatch):
    import swarmbench.judge as J
    from tests.test_judge_two_pass import _default, _run

    rd = RunDir.create("impossible-math", base=tmp_path)
    big = json.dumps(list(range(1_100_000))).encode()  # over the 4 MB comparison cap
    end = {**END, "out/pool.json": (big, 2001)}
    _tar(rd.root / "workspace" / "swarm" / "start.tar.gz", START)
    _tar(rd.root / "workspace" / "swarm" / "end.tar.gz", end)
    listed = [_entry("new1.csv", "added", b"a\n", 2001, "agent-1")]
    build_mock_log(rd.logs, workspace_diff={"swarm": {"changes": listed, "total_changes": 5, "truncated": True,
                                                      "notes": []}})
    monkeypatch.setattr(J, "default_cap", lambda settings: 100.0)
    r = _run(rd, _default)
    assert r.fully_assessed and r.gaps == [] and not r.limits
    assert any("compared the other 4 from the start and end snapshots" in n for n in r.technical_notes)
    assert any("1 large data file the agents generated was compared only in part" in n and "out/pool.json" in n
               for n in r.technical_notes)
    md = rd.report_md.read_text()
    assert "What limits this report" not in md and "- Note: 1 large data file" in md
