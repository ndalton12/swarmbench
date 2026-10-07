"""The root snapshot walk never follows symlinks out of the workspace (run on the host)."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile

from swarmbench.engine.snapshot import _SNAPSHOT


def run_snapshot(root, out):  # type: ignore[no-untyped-def]
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            _SNAPSHOT,
            str(root),
            str(out),
            str(1 << 20),
            str(1 << 24),
            str(1 << 24),
            "1000",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_links_are_recorded_never_followed(tmp_path):
    tmp_path = tmp_path.resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("host secret\n")
    ws = tmp_path / "ws"
    (ws / "notes").mkdir(parents=True)
    (ws / "notes" / "a.txt").write_text("a\n")
    (ws / "escape").symlink_to(outside)  # a folder swapped for a link to somewhere else
    (ws / "file-link").symlink_to(outside / "secret.txt")
    out = tmp_path / "snap.tar.gz"

    data = run_snapshot(ws, out)
    manifest = data["manifest"]
    assert manifest["notes"]["type"] == "dir" and manifest["notes/a.txt"]["sha256"]
    assert manifest["escape"] == {**manifest["escape"], "type": "link", "target": str(outside)}
    assert manifest["file-link"]["type"] == "link"
    assert not any("secret" in k for k in manifest)  # nothing under the link was read

    with tarfile.open(out) as t:
        names = t.getnames()
        assert "notes/a.txt" in names and t.getmember("escape").issym()
        assert not any("secret.txt" in n for n in names)
        assert all(
            b"host secret" not in (t.extractfile(m).read() if m.isfile() else b"") for m in t.getmembers()
        )
