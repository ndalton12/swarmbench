"""swarm report: print a run's report.md. Fake engine and judge only."""

import os
from contextlib import contextmanager

import pytest
from rich.console import Console
from typer.testing import CliRunner

from swarmbench import cli
from swarmbench.paths import list_runs
from swarmbench.runner import display, procs, runs
from swarmbench.status import StatusWriter, read_status

runner = CliRunner()

REPORT = "# Report\n\n**Verdict: minor.** The swarm claimed success.\n\n## Concerns\n\n- agent-2 edited the checker\n"


@pytest.fixture(autouse=True)
def plain_output(monkeypatch):
    out = Console(width=120, force_terminal=False, no_color=True, highlight=False)
    err = Console(width=120, force_terminal=False, no_color=True, highlight=False, stderr=True)
    for module in (cli, display):
        monkeypatch.setattr(module, "console", out)
        monkeypatch.setattr(module, "err", err)


def swarm(*args):
    return runner.invoke(cli.app, [str(a) for a in args])


@pytest.fixture
def finished_run(runs_base, scenario, fakes):
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    run_dir.report_md.write_text(REPORT)
    return run_dir


def test_report_by_any_reference(finished_run):
    for ref in (
        finished_run.run_id,
        runs.short_id(finished_run.run_id),
        finished_run.run_id[5:],
        str(finished_run.root),
    ):
        result = swarm("report", ref)
        assert result.exit_code == 0, result.output
        assert "Verdict: minor." in result.output and "agent-2 edited the checker" in result.output
        assert "**" not in result.output  # rendered, not raw Markdown


def test_report_latest(finished_run):
    result = swarm("report", "--latest")
    assert result.exit_code == 0 and "Concerns" in result.output


def test_report_needs_a_run_or_latest(finished_run):
    assert swarm("report").exit_code == 1
    assert swarm("report", finished_run.run_id, "--latest").exit_code == 1


def test_no_report_says_why(runs_base, scenario, fakes):
    s, _ = runs.resolve(scenario, {})
    run_dir = runs.prepare(s, runs.Launch(scenario_path=str(scenario)))
    status = read_status(run_dir)
    me = {"pid": os.getpid(), "pid_started": procs.start_time(os.getpid())}
    StatusWriter(run_dir, status.model_copy(update={"state": "running", **me}))
    result = swarm("report", run_dir.run_id)
    assert result.exit_code == 1 and "still running" in result.output

    StatusWriter(run_dir, status.model_copy(update={"state": "judging", **me}))
    assert "being judged" in swarm("report", run_dir.run_id).output

    StatusWriter(run_dir, status.model_copy(update={"state": "failed", "error": "no docker"}))
    out = swarm("report", run_dir.run_id).output
    assert "ended as failed (no docker)" in out and f"swarm judge {run_dir.run_id}" in out


def test_long_reports_go_through_a_pager(finished_run, monkeypatch):
    finished_run.report_md.write_text(REPORT + "\n".join(f"- line {i}" for i in range(200)))
    paged = []

    class Terminal(Console):
        @contextmanager
        def pager(self, *args, **kwargs):
            paged.append(True)
            yield

    term = Terminal(width=100, height=30, force_terminal=True, no_color=True)
    monkeypatch.setattr(cli, "console", term)
    assert swarm("report", finished_run.run_id).exit_code == 0
    assert paged == [True]
    assert swarm("report", finished_run.run_id, "--no-pager").exit_code == 0
    assert paged == [True]  # not paged again


def test_short_reports_are_not_paged(finished_run, monkeypatch):
    class Terminal(Console):
        def pager(self, *args, **kwargs):
            raise AssertionError("should not page a short report")

    monkeypatch.setattr(cli, "console", Terminal(width=100, height=40, force_terminal=True, no_color=True))
    assert swarm("report", finished_run.run_id).exit_code == 0


def test_run_and_judge_print_the_report_command(runs_base, scenario, fakes):
    result = swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    assert f"swarm report {run_dir.run_id}" in result.output
    assert f"swarm report {run_dir.run_id}" in swarm("judge", run_dir.run_id).output
