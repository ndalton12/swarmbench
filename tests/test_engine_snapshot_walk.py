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


def run_with_build_dirs(root, out, max_total=1 << 24):  # type: ignore[no-untyped-def]
    result = subprocess.run(
        [sys.executable, "-I", "-c", _SNAPSHOT, str(root), str(out), str(1 << 20), str(max_total),
         str(1 << 24), "1000", "target,node_modules", "1024"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(result.stdout)


def test_build_output_is_saved_last_so_it_never_crowds_out_other_files(tmp_path):
    ws = tmp_path / "ws"
    (ws / "app" / "target" / "release").mkdir(parents=True)
    (ws / "app" / "target" / "release" / "big.rlib").write_bytes(b"x" * 150_000)
    (ws / "app" / "target" / "release" / "reaper.sh").write_text(
        "#!/bin/sh\npkill -u u02\n"
    )  # small: in order
    (ws / "app" / "zz-src.rs").write_text("fn main() {}\n" * 1000)  # sorts after target/
    out = tmp_path / "snap.tar.gz"

    # the budget fits the source but not the build output as well
    data = run_with_build_dirs(ws, out, max_total=100_000)
    assert data["truncated"] == ["app/target/release/big.rlib"]  # still listed: a gap, not hidden
    assert data["manifest"]["app/target/release/big.rlib"]["skipped"] == "size cap"
    with tarfile.open(out) as t:
        names = t.getnames()
    assert "app/zz-src.rs" in names and "app/target/release/reaper.sh" in names

    # with room for everything, build output is archived like any file
    data = run_with_build_dirs(ws, tmp_path / "all.tar.gz")
    assert data["truncated"] == []
    with tarfile.open(tmp_path / "all.tar.gz") as t:
        assert t.extractfile("app/target/release/big.rlib").read() == b"x" * 150_000


def test_a_deferred_folder_swapped_for_a_link_is_not_followed(tmp_path):
    # the second pass reopens folders without following links, like the first
    import shutil

    from swarmbench.engine import snapshot

    tmp_path = tmp_path.resolve()
    outside = tmp_path / "outside" / "release"
    outside.mkdir(parents=True)
    (outside / "big.rlib").write_bytes(b"host secret" * 20_000)
    ws = tmp_path / "ws"
    (ws / "target" / "release").mkdir(parents=True)
    (ws / "target" / "release" / "big.rlib").write_bytes(b"y" * 200_000)
    # swap the folder for a link right after the first pass lists the file
    script = snapshot._SNAPSHOT.replace(
        "for parts, name, rel in deferred:",
        f"import shutil; shutil.rmtree({str(ws / 'target')!r}); os.symlink({str(tmp_path / 'outside')!r}, "
        f"{str(ws / 'target')!r})\nfor parts, name, rel in deferred:",
    )
    assert script != snapshot._SNAPSHOT
    out = tmp_path / "snap.tar.gz"
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ws), str(out), str(1 << 20), str(1 << 24), str(1 << 24), "1000",
         "target", "1024"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    manifest = json.loads(result.stdout)["manifest"]
    assert "target/release/big.rlib" not in manifest
    with tarfile.open(out) as t:
        assert all(
            b"host secret" not in (t.extractfile(m).read() if m.isfile() else b"") for m in t.getmembers()
        )
    shutil.rmtree(tmp_path / "outside")
