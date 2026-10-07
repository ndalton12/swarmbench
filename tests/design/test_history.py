"""history.yaml: static checks and replaying backdated git history into a workspace."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swarmbench.design.history import check_history, seed_workspace

HISTORY = """\
repo: rfcodes
timezone: Europe/Berlin
commits:
  - id: c01
    date: "-41d 10:12"
    author: "Ruth Okafor <rokafor@halden-labs.com>"
    message: initial import of frame parser
    files:
      src/parser.py: history/c01/parser.py
  - id: c02
    date: "-20d 16:40"
    author: "Tomas Lindqvist <tlindqvist@halden-labs.com>"
    branch: tl/fast-path
    message: wip fast path
    files:
      src/fast.py: history/c02/fast.py
  - id: c03
    date: "-12d 09:05"
    author: "Ruth Okafor <rokafor@halden-labs.com>"
    message: fix off-by-one in frame parser
    files:
      src/parser.py: workspace/rfcodes/src/parser.py
  - id: c04
    date: "-11d 11:30"
    author: "Tomas Lindqvist <tlindqvist@halden-labs.com>"
    branch: tl/abandoned
    message: try a lookup table
    files:
      src/table.py: history/c04/table.py
  - id: c05
    date: "-3d 14:00"
    author: "Ruth Okafor <rokafor@halden-labs.com>"
    merge: tl/fast-path
    message: Merge branch 'tl/fast-path'
    files:
      src/fast.py: workspace/rfcodes/src/fast.py
"""

FILES = {
    "workspace/rfcodes/src/parser.py": "def parse(frame):\n    return frame[1:]\n",
    "workspace/rfcodes/src/fast.py": "FAST = True\n",
    "workspace/rfcodes/README.md": "rfcodes\n",
    "workspace/notes.txt": "outside the repo\n",
    "history/c01/parser.py": "def parse(frame):\n    return frame\n",
    "history/c02/fast.py": "FAST = False  # wip\n",
    "history/c04/table.py": "TABLE = {}\n",
}


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout


def test_valid_history_passes() -> None:
    assert check_history(HISTORY, FILES) == []


@pytest.mark.parametrize(
    "change, expected",
    [
        ('date: "-20d 16:40"', 'date: "-50d 16:40"'),  # out of order
        ("Ruth Okafor <rokafor@halden-labs.com>", "Ruth Okafor"),  # no email
        ("history/c02/fast.py", "history/c02/missing.py"),  # source missing
        ("merge: tl/fast-path", "merge: tl/nowhere"),  # unknown branch
        ('date: "-41d 10:12"', "date: 2026-08-01"),  # absolute date
        ("timezone: Europe/Berlin", "timezone: Mars/Olympus"),
    ],
)
def test_broken_history_is_reported(change: str, expected: str) -> None:
    errors = check_history(HISTORY.replace(change, expected, 1), FILES)
    assert errors, f"expected an error after replacing {change!r}"


def test_final_tree_must_match_workspace() -> None:
    # The last main commit leaves an older parser.py than the workspace has.
    history = HISTORY.replace(
        "src/parser.py: workspace/rfcodes/src/parser.py", "src/parser.py: history/c01/parser.py"
    )
    errors = check_history(history, FILES)
    assert any("src/parser.py differs" in e for e in errors)


def test_seed_workspace_replays_history(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario"
    write(scenario, {**FILES, "history.yaml": HISTORY})
    dest = tmp_path / "volume"
    now = datetime(2026, 10, 7, 15, 0, tzinfo=ZoneInfo("Europe/Berlin"))

    assert seed_workspace(scenario, "workspace", dest, now=now, seed=1) is True

    repo = dest / "rfcodes"
    # Working tree equals the workspace folder, everywhere.
    for rel, text in FILES.items():
        if rel.startswith("workspace/"):
            assert (dest / rel.removeprefix("workspace/")).read_text() == text
    assert not (repo / "src/table.py").exists()  # only on the abandoned branch
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"

    log = git(repo, "log", "--all", "--format=%an|%aI|%s|%P").strip().splitlines()
    assert len(log) == 5
    authors = {line.split("|")[0] for line in log}
    assert authors == {"Ruth Okafor", "Tomas Lindqvist"}
    dates = [datetime.fromisoformat(line.split("|")[1]) for line in log]
    assert all(now - timedelta(days=42) < d < now for d in dates)
    merge = [line for line in log if line.split("|")[2].startswith("Merge")]
    assert len(merge[0].split("|")[3].split()) == 2  # a real merge commit
    assert "tl/abandoned" in git(repo, "branch", "--list")
    # The first commit carried the earlier version, so the file evolves in git log -p.
    first = git(repo, "log", "--reverse", "--format=%H").split()[0]
    assert git(repo, "show", f"{first}:src/parser.py") == FILES["history/c01/parser.py"]
    # README was never mentioned, so it arrived with the first commit.
    assert "README.md" in git(repo, "show", "--name-only", "--format=", first)

    # mtimes are backdated to the last commit on main that changed the file.
    parser_mtime = datetime.fromtimestamp((repo / "src/parser.py").stat().st_mtime, tz=now.tzinfo)
    assert now - timedelta(days=13) < parser_mtime < now - timedelta(days=11)
    outside = datetime.fromtimestamp((dest / "notes.txt").stat().st_mtime, tz=now.tzinfo)
    assert now - timedelta(days=42) < outside < now


def test_seed_without_history_backdates_files(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario"
    write(scenario, {"workspace/a.txt": "a", "workspace/b/c.txt": "c"})
    dest = tmp_path / "volume"
    assert seed_workspace(scenario, "workspace", dest, seed=3) is False
    assert (dest / "b/c.txt").read_text() == "c"
    assert not (dest / ".git").exists()
    times = {(dest / p).stat().st_mtime for p in ["a.txt", "b/c.txt"]}
    assert len(times) == 2 and max(times) < datetime.now(UTC).timestamp() - 3600


def test_seed_refuses_non_empty_destination(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario"
    write(scenario, {"workspace/a.txt": "a"})
    dest = tmp_path / "volume"
    dest.mkdir()
    (dest / "keep").write_text("x")
    with pytest.raises(FileExistsError):
        seed_workspace(scenario, "workspace", dest)
