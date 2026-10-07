"""Workspace snapshots at start and end, and the per-file diff in the store."""

from __future__ import annotations

import tarfile

import pytest

from tests.engine_helpers import make_scenario, requires_docker, run_mock

pytestmark = [requires_docker, pytest.mark.docker]


def test_workspace_snapshots_and_diff(tmp_path):
    folder = make_scenario(tmp_path, **{"swarm.agents": 1, "swarm.messaging": "off", "advanced.extra": {}})
    (folder / "workspace" / "data.csv").write_text("a,b\n1,2\n")
    (folder / "workspace" / "old.txt").write_text("to be removed\n")
    script = [
        (
            "shell",
            "cd /workspace && echo '3,4' >> data.csv && rm old.txt && echo new > new.txt "
            "&& echo secret > private.txt && chmod 600 private.txt && ln -s /etc/passwd link "
            "&& mkfifo pipe",
        ),
        ("final", "done"),
    ]
    sample, run_dir, _ = run_mock(folder, tmp_path, {"agent-1": script})

    diff = sample.store["swarm_workspace_diff"]["swarm"]
    changes = {c["path"]: c for c in diff["changes"]}
    assert changes["/workspace/data.csv"]["change"] == "changed"
    assert changes["/workspace/data.csv"]["uid"] == 0  # root-owned seed file, edited through the group
    assert (
        changes["/workspace/old.txt"]["change"] == "deleted" and changes["/workspace/old.txt"]["uid"] is None
    )
    assert changes["/workspace/new.txt"]["agent"] == "agent-1"
    assert changes["/workspace/new.txt"]["change"] == "added" and changes["/workspace/new.txt"]["uid"] == 2001
    # a private file is still captured, by its owner
    assert (
        changes["/workspace/private.txt"]["sha_after"] and not changes["/workspace/private.txt"]["unverified"]
    )
    assert changes["/workspace/link"]["type"] == "link"
    assert "/workspace/pipe" not in changes  # special files are skipped
    assert "/workspace/README.md" not in changes
    assert diff["truncated"] is False

    start = run_dir.root / diff["start_archive"]
    end = run_dir.root / diff["end_archive"]
    with tarfile.open(start) as t:
        assert t.extractfile("old.txt").read() == b"to be removed\n"
    with tarfile.open(end) as t:
        names = t.getnames()
        assert "private.txt" in names and "old.txt" not in names
        assert t.extractfile("data.csv").read() == b"a,b\n1,2\n3,4\n"
        assert t.getmember("link").issym() and t.getmember("link").linkname == "/etc/passwd"
