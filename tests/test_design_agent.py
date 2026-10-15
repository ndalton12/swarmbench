"""swarm design: a coding agent designs the scenario by following the design skill, in a working
copy, and only new scenario folders come back. A fake agent program stands in for Claude Code and
Codex; nothing is spent."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import sys
from pathlib import Path

import psutil
import pytest
from rich.console import Console
from typer.testing import CliRunner

from swarmbench import cli
from swarmbench.design import agent
from swarmbench.paths import list_runs
from swarmbench.status import read_status
from tests.conftest import make_scenario, wait_for

runner = CliRunner()


@pytest.fixture
def fake_agent(tmp_path, monkeypatch):
    """Put only our shell script and system utilities on the agent's PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    program = bin_dir / "codex"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin")
    # run() prepends Python's bin directory; refuse to run if that would shadow our fake.
    path = f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"

    def install(body):
        program.write_text(f"#!/bin/sh\nset -eu\n{body}\n")
        program.chmod(0o755)
        assert shutil.which("codex", path=path) == str(program)
        return program

    return install


@pytest.fixture
def design_result(tmp_path, monkeypatch, fake_agent):
    """Keep CLI validation real, but replace the design session with a recorded call."""
    fake_agent("exit 99")
    out = Console(width=250, force_terminal=False, no_color=True, highlight=False)
    err = Console(width=250, force_terminal=False, no_color=True, highlight=False, stderr=True)
    monkeypatch.setattr(cli, "console", out)
    monkeypatch.setattr(cli, "err", err)
    result = agent.Result(
        returncode=0,
        published=[make_scenario(tmp_path / "scenarios" / "new")],
        skipped=[],
        other_changes=["changed docs/realism.md"],
        session=tmp_path / "session",
    )
    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(agent, "run", run)
    return result, calls


def test_tasks_point_at_the_skill_and_say_nobody_will_answer():
    new = agent.new_task("rival market makers on one venue, zero-sum")
    assert str(agent.SKILL) in new and "rival market makers" in new and "without a person" in new
    assert "only new scenario folders are kept" in new and "Real runs are disabled" in new
    revise = agent.iterate_task(Path("scenarios/x"), [Path("/r/a"), Path("/r/b")])
    assert "Revising a scenario after runs" in revise and "- /r/a" in revise and "- /r/b" in revise
    moment = agent.moment_task(Path("/r/a"), "agent edits the checker", Path("scenarios/x"))
    assert "from a moment" in moment and "agent edits the checker" in moment and "scenarios/x" in moment
    assert agent.SKILL.as_posix() == ".claude/skills/design-scenario/SKILL.md"
    assert (agent.REPO_ROOT / agent.SKILL).is_file()


def test_command_lines_are_narrow():
    claude = agent.command("claude", "do it", model="claude-opus-5-5", max_cost=12, readable=[Path("/runs/a")])
    assert claude[:3] == ["claude", "-p", "do it"]
    assert "acceptEdits" in claude and "Write" in claude and "Bash(swarm check *)" in claude
    assert not any(t.startswith(("Bash(swarm run", "Bash(swarm screen", "Bash(uv run swarm")) for t in claude)
    assert claude[claude.index("--output-format") + 1] == "stream-json"
    assert claude[claude.index("--max-budget-usd") + 1] == "12"
    assert claude[claude.index("--add-dir") + 1] == "/runs/a"
    codex = agent.command("codex", "do it", last_message=Path("/tmp/last.txt"), workdir=Path("/w"))
    assert codex[:2] == ["codex", "exec"] and codex[-1] == "do it"
    assert codex[codex.index("--sandbox") + 1] == "workspace-write" and codex[codex.index("--cd") + 1] == "/w"
    assert "--max-budget-usd" not in codex  # Codex has no dollar cap
    with pytest.raises(ValueError):
        agent.command("gemini", "do it")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    make_scenario(repo / "scenarios" / "old")
    (repo / "docs").mkdir()
    (repo / "docs" / "realism.md").write_text("rules\n")
    skill = repo / agent.SKILL
    skill.parent.mkdir(parents=True)
    skill.write_text("guide\n")
    (repo / "README.md").write_text("readme\n")
    return repo


def test_agent_works_in_a_copy_and_only_new_scenarios_come_back(tmp_path, fake_agent):
    """Edits stay in the session, while new scenarios and readable output are kept."""
    repo = _repo(tmp_path)
    original_prompt = (repo / "scenarios/old/prompt.md").read_text()
    fake_agent("""
pwd
printf 'session=%s\nruns=%s\n' "$SWARMBENCH_DESIGN_SESSION" "$SWARMBENCH_RUNS"
mkdir -p scenarios/new/workspace
printf 'new prompt\n' > scenarios/new/prompt.md
printf 'new data\n' > scenarios/new/workspace/data.txt
printf 'changed rules\n' > docs/realism.md
printf 'changed prompt\n' > scenarios/old/prompt.md
printf 'design ready\n'
printf 'agent diagnostic\n' >&2
""")
    lines = []
    result = agent.run("codex", "make a scenario", "new", repo=repo, say=lines.append)
    work = result.session / "work"
    assert result.returncode == 0
    assert result.session.parent == repo / "runs/designs"
    assert work.is_dir() and work.resolve() != repo.resolve()
    assert Path(lines[0]).resolve() == work.resolve()
    assert lines[1:] == [
        "session=1", f"runs={work / 'runs'}", "design ready", "agent diagnostic",
    ]
    assert result.log.read_text().splitlines() == lines
    assert (result.session / "task.txt").read_text() == "make a scenario\n"
    assert result.published == [repo / "scenarios/new"]
    assert result.skipped == []
    assert (repo / "scenarios/new/prompt.md").read_text() == "new prompt\n"
    assert (repo / "scenarios/new/workspace/data.txt").read_text() == "new data\n"
    assert (repo / "docs/realism.md").read_text() == "rules\n"
    assert (repo / "scenarios/old/prompt.md").read_text() == original_prompt
    assert (work / "docs/realism.md").read_text() == "changed rules\n"
    assert result.other_changes == ["changed docs/realism.md", "changed scenarios/old/prompt.md"]
    assert (work / agent.SKILL).read_text() == "guide\n"
    assert (work / "README.md").read_text() == "readme\n"


def test_a_scenario_created_in_the_repo_during_a_session_is_skipped(tmp_path, fake_agent):
    """A concurrent publication wins; the agent's version stays in its working copy."""
    repo = _repo(tmp_path)
    fake_agent("mkdir scenarios/rival\nprintf 'agent copy\n' > scenarios/rival/prompt.md\necho ready")

    def publish_first(line):
        assert line == "ready"
        make_scenario(repo / "scenarios/rival")

    result = agent.run("codex", "make a rival", "new", repo=repo, say=publish_first)
    assert result.returncode == 0
    assert result.published == [] and result.skipped == ["rival"]
    assert result.other_changes == []
    assert (repo / "scenarios/rival/prompt.md").read_text() == "Do the work.\n"
    assert (result.session / "work/scenarios/rival/prompt.md").read_text() == "agent copy\n"


def test_two_sessions_have_their_own_folders_and_logs(tmp_path, fake_agent):
    """Even consecutive sessions of the same kind keep separate work and logs."""
    repo = _repo(tmp_path)
    fake_agent("echo ready")
    first = agent.run("codex", "first task", "new", repo=repo, say=lambda line: None)
    second = agent.run("codex", "second task", "new", repo=repo, say=lambda line: None)
    assert first.session != second.session
    for result, task in ((first, "first task"), (second, "second task")):
        assert result.session.parent == repo / "runs/designs"
        assert (result.session / "work").is_dir()
        assert result.log.read_text() == "ready\n"
        assert (result.session / "task.txt").read_text() == f"{task}\n"
        assert result.returncode == 0 and result.published == [] and result.other_changes == []


def test_changes_separate_new_scenario_folders_from_other_edits():
    """New folders are sorted and deduplicated; additions, edits and deletions are described."""
    before = {"README.md": "same", "docs/old.md": "old", "scenarios/old/prompt.md": "old"}
    after = {
        "README.md": "same",
        "docs/new.md": "new",
        "scenarios/old/prompt.md": "changed",
        "scenarios/old/extra.md": "new",
        "scenarios/zebra/prompt.md": "new",
        "scenarios/zebra/workspace/data.txt": "new",
        "scenarios/alpha/prompt.md": "new",
        "scenarios/loose.md": "new",
    }
    result = agent.changes(before, after, {"old"})
    assert result.new_folders == ["alpha", "zebra"]
    assert result.other == [
        "added docs/new.md", "deleted docs/old.md", "added scenarios/loose.md",
        "added scenarios/old/extra.md", "changed scenarios/old/prompt.md",
    ]
    assert agent.changes(before, before, {"old"}) == agent.Changes()
    assert agent.changes({}, {}, set()) == agent.Changes()


def test_fingerprint_hashes_contents_and_ignores_runs_caches_and_symlinks(tmp_path):
    """Only regular source files count, with paths relative to the working folder."""
    assert agent.fingerprint(tmp_path) == {}
    for name in ("docs", "runs", "__pycache__", "docs/__pycache__"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "README.md").write_bytes(b"readme\n")
    (tmp_path / "docs/realism.md").write_bytes(b"rules\n")
    for name in ("runs/log.txt", "__pycache__/a.pyc", "docs/__pycache__/b.pyc"):
        (tmp_path / name).write_bytes(b"ignored")
    (tmp_path / "link.md").symlink_to(tmp_path / "README.md")
    before = agent.fingerprint(tmp_path)
    assert before == {
        "README.md": hashlib.sha256(b"readme\n").hexdigest(),
        "docs/realism.md": hashlib.sha256(b"rules\n").hexdigest(),
    }
    (tmp_path / "docs/realism.md").write_bytes(b"edits\n")
    after = agent.fingerprint(tmp_path)
    assert after["README.md"] == before["README.md"]
    assert after["docs/realism.md"] == hashlib.sha256(b"edits\n").hexdigest()
    assert after["docs/realism.md"] != before["docs/realism.md"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "  Reading the skill.\n"},
            {"type": "text", "text": "  "},
            {"type": "tool_use", "name": "Bash", "input": {"command": "swarm check scenarios/new"}},
        ]}}), ["Reading the skill.", "> Bash swarm check scenarios/new"]),
        (json.dumps({"type": "result", "subtype": "success", "total_cost_usd": 1.234}),
         ["Session ended: success, $1.23"]),
        ('{"type":"result"}', ["Session ended: done"]),
        ("plain output\n", ["plain output"]),
        ("{broken json\n", ["{broken json"]),
        (" \n", []),
        ('{"unrelated":true}', []),
        ('{"type":"system","subtype":"init"}', []),
        ("[]", []),
        ("null", []),
        ('"text in JSON"', []),
    ],
)
def test_claude_events_become_readable_lines(line, expected):
    """Assistant text, commands and cost are readable; irrelevant JSON is quiet."""
    assert agent.describe_event(line) == expected


def test_interrupting_output_stops_the_agent_and_its_child(tmp_path, fake_agent):
    """A failing say callback must not leave the shell or its long-running child alive."""
    repo = _repo(tmp_path)
    fake_agent("""
sleep 60 &
child=$!
trap 'wait "$child"; exit 0' TERM
printf '%s %s\n' "$$" "$child"
wait "$child"
""")
    pids = []

    def interrupted(line):
        pids.extend(int(pid) for pid in line.split())
        assert len(pids) == 2 and all(psutil.pid_exists(pid) for pid in pids)
        raise RuntimeError("output interrupted")

    try:
        with pytest.raises(RuntimeError, match="output interrupted"):
            agent.run("codex", "wait", "new", repo=repo, say=interrupted)
        assert len(pids) == 2
        wait_for(lambda: all(not psutil.pid_exists(pid) for pid in pids), timeout=5)
    finally:
        # If cleanup regresses, do not leak the test's processes into the rest of the suite.
        for pid in reversed(pids):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_design_new_checks_what_was_written_and_lists_unapplied_changes(design_result):
    """The CLI validates the published scenario and explains edits that stayed in the session."""
    _, calls = design_result
    result = runner.invoke(cli.app, [
        "design", "new", "rival market makers", "--agent", "codex", "--model", "test-model",
        "--max-cost", "3",
    ])
    assert result.exit_code == 0, result.output
    assert "Wrote" in result.output and "is valid" in result.output
    assert "Not applied" in result.output and "changed docs/realism.md" in result.output
    (args, kwargs), = calls
    assert args == ("codex", agent.new_task("rival market makers"), "new")
    assert kwargs["model"] == "test-model" and kwargs["max_cost"] == 3


@pytest.mark.parametrize(("returncode", "published", "message"), [
    (7, True, "exit 7"),
    (0, False, "No new scenario folder"),
])
def test_design_new_fails_when_the_agent_failed_or_wrote_nothing(
    design_result, returncode, published, message
):
    """Neither an agent error nor an empty session is a successful design."""
    session, calls = design_result
    session.returncode = returncode
    if not published:
        session.published = []
    result = runner.invoke(cli.app, ["design", "new", "an idea", "--agent", "codex"])
    assert result.exit_code == 1, result.output
    assert message in result.output and len(calls) == 1


def test_design_new_refuses_an_unknown_agent(design_result):
    """Bad agent names fail before any session starts."""
    _, calls = design_result
    result = runner.invoke(cli.app, ["design", "new", "an idea", "--agent", "gemini"])
    assert result.exit_code == 1 and "Unknown agent" in result.output
    assert calls == []


def test_design_iterate_needs_a_scenario_file(tmp_path, design_result):
    """An existing folder without scenario.yaml cannot be revised."""
    _, calls = design_result
    result = runner.invoke(cli.app, [
        "design", "iterate", str(tmp_path), "--from", "past-run", "--agent", "codex",
    ])
    assert result.exit_code == 1 and "isn't a scenario folder" in result.output
    assert calls == []


def test_design_iterate_passes_the_runs_and_external_scenario(tmp_path, scenario, design_result):
    """Repeated evidence paths and the source scenario reach the isolated working copy."""
    _, calls = design_result
    run_dirs = [tmp_path / "run-a", tmp_path / "run-b"]
    for folder in run_dirs:
        (folder / "logs").mkdir(parents=True)
    result = runner.invoke(cli.app, [
        "design", "iterate", str(scenario), "--from", str(run_dirs[0]), "--from", str(run_dirs[1]),
        "--agent", "codex",
    ])
    assert result.exit_code == 0, result.output
    (args, kwargs), = calls
    resolved = [folder.resolve() for folder in run_dirs]
    assert args == ("codex", agent.iterate_task(Path("scenarios/tiny"), resolved), "iterate")
    assert kwargs["readable"] == resolved
    assert kwargs["extra_scenarios"] == [scenario.resolve()]


@pytest.mark.parametrize("with_scenario", [False, True])
def test_design_moment_passes_the_moment_and_optional_scenario(
    tmp_path, scenario, design_result, with_scenario
):
    """A moment can stand alone or carry its source scenario into the working copy."""
    _, calls = design_result
    run_dir = tmp_path / "past-run"
    (run_dir / "logs").mkdir(parents=True)
    args = ["design", "moment", str(run_dir), "agent edits the checker", "--agent", "codex"]
    if with_scenario:
        args += ["--scenario", str(scenario)]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    (args, kwargs), = calls
    source = Path("scenarios/tiny") if with_scenario else None
    assert args == (
        "codex", agent.moment_task(run_dir.resolve(), "agent edits the checker", source), "moment",
    )
    assert kwargs["readable"] == [run_dir.resolve()]
    assert kwargs["extra_scenarios"] == ([scenario.resolve()] if with_scenario else [])


def test_design_sessions_refuse_real_runs_but_allow_attached_dry_runs(
    runs_base, scenario, fakes, monkeypatch
):
    """The design guard blocks spending while letting the fake dry run finish normally."""
    monkeypatch.setenv("SWARMBENCH_DESIGN_SESSION", "1")
    monkeypatch.setenv("XDG_DATA_HOME", str(runs_base.parent / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(runs_base.parent / "cache"))
    refused = runner.invoke(cli.app, ["run", str(scenario), "--attached"])
    assert refused.exit_code == 1 and "inside a design session" in refused.output
    assert list_runs(runs_base) == []
    allowed = runner.invoke(cli.app, ["run", str(scenario), "--dry-run", "--attached"])
    assert allowed.exit_code == 0, allowed.output
    (run_dir,) = list_runs(runs_base)
    assert read_status(run_dir).state == "done"


@pytest.mark.parametrize("command", ["screen", "judge"])
def test_design_sessions_refuse_screening_and_judging(runs_base, scenario, fakes, monkeypatch, command):
    """Other spending commands stop at the same guard, before starting any work."""
    monkeypatch.setenv("SWARMBENCH_DESIGN_SESSION", "1")
    args = [command, str(scenario)] if command == "screen" else [command, "past-run"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 1 and "inside a design session" in result.output
    assert list_runs(runs_base) == []
