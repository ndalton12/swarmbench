"""The swarm command line, against a fake engine and judge. No models, no Docker."""

import json

import pytest
from typer.testing import CliRunner

from swarmbench import cli, engine
from swarmbench.paths import list_runs
from swarmbench.runner import control, docker, experiment, listing, procs
from swarmbench.status import read_status
from tests.conftest import make_scenario, wait_for

runner = CliRunner()


@pytest.fixture(autouse=True)
def plain_output(monkeypatch):
    """Wide, uncoloured output that is easy to search."""
    from rich.console import Console

    from swarmbench.runner import display

    out = Console(width=250, force_terminal=False, no_color=True, highlight=False)
    err = Console(width=250, force_terminal=False, no_color=True, highlight=False, stderr=True)
    for module in (cli, display):
        monkeypatch.setattr(module, "console", out)
        monkeypatch.setattr(module, "err", err)


@pytest.fixture
def no_docker(monkeypatch):
    """Record docker commands instead of running them."""
    calls = []

    def fake(*args, timeout=120):
        calls.append(args)
        return docker.subprocess.CompletedProcess(["docker", *args], 0, "", "")

    monkeypatch.setattr(docker, "docker", fake)
    return calls


def swarm(*args, input=None):
    return runner.invoke(cli.app, [str(a) for a in args], input=input)


# ---- swarm run ---------------------------------------------------------------------------


def test_run_dry_run_prints_verdict_cost_and_viewer_commands(runs_base, scenario, fakes):
    result = swarm("run", scenario, "--dry-run")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Dry run" in out and "Verdict: minor" in out
    assert "Fake headline (minor)" in out and "The fake swarm did fake things." in out
    assert "Cost: swarm $1.00, judge $0.25, total $1.25" in out
    (run_dir,) = list_runs(runs_base)
    assert f"swarm view {run_dir.root}" in out and f"swarm view {run_dir.root} --scout" in out
    assert read_status(run_dir).state == "done"


def test_run_flags_reach_the_engine(runs_base, tmp_path, fakes, monkeypatch):
    folder = make_scenario(
        tmp_path / "rivals",
        "name: rivals\nswarm: {agents: 2}\nteams: [{name: red, agents: 5}, {name: blue}]\n",
    )
    seen = {}

    def run_scenario(scenario, run_dir, status, dry_run=False):
        seen["agents"] = [t.agents for t in scenario.resolved_teams()]
        seen["effort"] = scenario.swarm.effort
        seen["dry_run"] = dry_run
        return []

    monkeypatch.setattr(engine, "run_scenario", run_scenario)
    result = swarm("run", folder, "--agents", 3, "--effort", "high", "--dry-run")
    assert result.exit_code == 0, result.output
    assert seen == {"agents": [3, 3], "effort": "high", "dry_run": True}


def test_run_estimate_and_confirmation(runs_base, scenario, fakes, monkeypatch):
    monkeypatch.setenv("SWARMBENCH_CONFIRM_ABOVE", "1")
    result = swarm("run", scenario, input="n\n")
    assert result.exit_code == 1
    # 200k tokens at $10/M = $2 for the swarm, plus the $1 minimum judge allowance.
    assert "Worst-case cost: $3.00" in result.output
    assert list_runs(runs_base) == []  # nothing launched

    result = swarm("run", scenario, "--yes")
    assert result.exit_code == 0, result.output
    assert len(list_runs(runs_base)) == 1


def test_run_below_threshold_does_not_ask(runs_base, scenario, fakes):
    result = swarm("run", scenario)  # worst case $3 is below the default $10 threshold
    assert result.exit_code == 0, result.output
    assert "Launch?" not in result.output


def test_run_refuses_cap_on_unpriced_model(runs_base, scenario, fakes):
    result = swarm("run", scenario, "--model", "openai/gpt-5.5", "--max-cost", 5, "--yes")
    assert result.exit_code == 1
    assert "no price for openai/gpt-5.5" in result.output
    assert list_runs(runs_base) == []


def test_run_unpriced_without_cap_shows_unknown(runs_base, tmp_path, fakes):
    folder = make_scenario(tmp_path / "s", "name: s\nswarm: {model: openai/gpt-5.5}\n")
    result = swarm("run", folder, input="y\n")
    assert "unknown" in result.output and "Launch anyway?" in result.output
    assert result.exit_code == 0, result.output


def test_run_bad_flag_value(runs_base, scenario, fakes):
    result = swarm("run", scenario, "--harness", "nonsense", "--dry-run")
    assert result.exit_code == 1 and "harness" in result.output


def test_run_failure_exit_code(runs_base, scenario, fakes, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no docker")

    monkeypatch.setattr(engine, "run_scenario", boom)
    result = swarm("run", scenario, "--dry-run")
    assert result.exit_code == 1 and "failed: RuntimeError: no docker" in result.output


# ---- detached runs, ps, stop -----------------------------------------------------------


def _state(run_dir):
    s = read_status(run_dir)
    return s.state if s else None


def test_detached_run_finishes_in_background(runs_base, scenario, fakes):
    result = swarm("run", scenario, "--dry-run", "--detach")
    assert result.exit_code == 0, result.output
    assert "in the background" in result.output
    (run_dir,) = list_runs(runs_base)
    wait_for(lambda: _state(run_dir) == "done")
    status = read_status(run_dir)
    assert status.verdict == "minor" and status.pid is not None
    assert "run finished: done" in run_dir.run_log.read_text()

    listed = swarm("list")
    assert run_dir.run_id in listed.output and "minor" in listed.output and "$1.25" in listed.output


def test_ps_and_graceful_stop(runs_base, scenario, fakes, monkeypatch, no_docker):
    monkeypatch.setenv("FAKE_RUN_SECONDS", "60")
    swarm("run", scenario, "--dry-run", "--detach")
    (run_dir,) = list_runs(runs_base)
    wait_for(lambda: _state(run_dir) == "running")

    ps = swarm("ps")
    assert run_dir.run_id in ps.output
    assert "running" in ps.output and "2/2" in ps.output and "1 high" in ps.output and "$1.00" in ps.output

    status = read_status(run_dir)
    stopped = swarm("stop", run_dir.run_id, "--timeout", 20)
    assert stopped.exit_code == 0, stopped.output
    assert f"{run_dir.run_id}: stopped" in stopped.output
    assert not procs.is_alive(status.pid, status.pid_started)
    assert _state(run_dir) == "stopped"
    assert (run_dir.root / "stop_requested").read_text() == "stopped by swarm stop"
    # The engine wound down by itself, so the run was never interrupted.
    assert "[swarm] signal" not in run_dir.run_log.read_text()
    assert no_docker == []  # a graceful stop leaves Docker to the run itself
    assert "No runs in progress" in swarm("ps").output


def test_stop_interrupts_a_run_that_does_not_wind_down(runs_base, scenario, fakes, monkeypatch, no_docker):
    monkeypatch.setenv("FAKE_RUN_SECONDS", "60")
    monkeypatch.setenv("FAKE_IGNORE_FILE", "1")
    swarm("run", scenario, "--dry-run", "--detach")
    (run_dir,) = list_runs(runs_base)
    wait_for(lambda: _state(run_dir) == "running")
    result = swarm("stop", run_dir.run_id, "--grace", 0.5, "--timeout", 20)
    assert f"{run_dir.run_id}: stopped" in result.output and "interrupting it" in result.output
    assert "[swarm] signal 2" in run_dir.run_log.read_text()
    assert _state(run_dir) == "stopped"


def test_hard_stop_kills_and_removes_containers(runs_base, scenario, fakes, monkeypatch, no_docker):
    monkeypatch.setenv("FAKE_RUN_SECONDS", "60")
    monkeypatch.setenv("FAKE_IGNORE_STOP", "1")
    monkeypatch.setattr(control, "TERM_GRACE", 1.0)
    swarm("run", scenario, "--dry-run", "--detach")
    (run_dir,) = list_runs(runs_base)
    wait_for(lambda: _state(run_dir) == "running")
    status = read_status(run_dir)

    soft = swarm("stop", run_dir.run_id, "--grace", 0.5, "--timeout", 1)
    assert soft.exit_code == 1 and "still shutting down" in soft.output
    assert procs.is_alive(status.pid, status.pid_started)

    hard = swarm("stop", run_dir.run_id, "--hard", "--grace", 0.5, "--timeout", 1)
    assert f"{run_dir.run_id}: killed" in hard.output
    assert not procs.is_alive(status.pid, status.pid_started)
    assert _state(run_dir) == "stopped"
    # docker compose down for the run's project, and lookups by the run's label.
    assert (
        "compose",
        "-p",
        f"fake-{run_dir.run_id}",
        "down",
        "--volumes",
        "--remove-orphans",
        "--timeout",
        "10",
    ) in no_docker
    assert any(f"label=swarmbench.run={run_dir.run_id}" in call for call in no_docker)


def test_ps_shows_died_runs(runs_base, scenario, fakes, monkeypatch, no_docker):
    from swarmbench.runner import runs
    from swarmbench.status import StatusWriter

    s, _ = runs.resolve(scenario, {})
    run_dir = runs.prepare(s, runs.Launch(scenario_path=str(scenario)))
    status = read_status(run_dir)
    StatusWriter(
        run_dir, status.model_copy(update={"state": "running", "pid": 999_999_99, "pid_started": 1.0})
    )
    assert "died" in swarm("ps").output
    cleaned = swarm("cleanup", "--yes")
    assert "marked failed" in cleaned.output
    assert _state(run_dir) == "failed"


# ---- experiments -----------------------------------------------------------------------


def _exp_file(tmp_path, scenario, name="mini", extra=""):
    f = tmp_path / f"{name}.yaml"
    f.write_text(
        f"name: {name}\nscenarios: [{scenario}]\nvary:\n  swarm.agents: [1, 2, 3]\nmax_parallel: 2\nmax_cost: 20\n{extra}"
    )
    return f


def test_experiment_foreground(runs_base, scenario, fakes, tmp_path, monkeypatch):
    monkeypatch.setattr(experiment.Supervisor, "poll", 0.1)
    result = swarm("experiment", _exp_file(tmp_path, scenario), "--dry-run")
    assert result.exit_code == 0, result.output
    assert "3 runs, at most 2 at a time" in result.output
    rows = listing.all_rows(experiment="mini")
    assert len(rows) == 3 and all(r.status.state == "done" for r in rows)
    assert (runs_base / "experiments" / "mini" / "summary.md").exists()


def test_experiment_detached_then_list(runs_base, scenario, fakes, tmp_path):
    result = swarm("experiment", _exp_file(tmp_path, scenario), "--dry-run", "--detach")
    assert result.exit_code == 0, result.output
    wait_for(lambda: (s := experiment.read_supervisor("mini")) and s.state == "done", timeout=60)

    listed = swarm("list", "--experiment", "mini")
    assert listed.exit_code == 0, listed.output
    for n in (1, 2, 3):
        assert f"swarm.agents={n}" in listed.output
    assert "Fake headline (minor)" in listed.output and "none noticed" in listed.output
    summary = (runs_base / "experiments" / "mini" / "summary.md").read_text()
    assert "| Run | Settings | State | Verdict | Headline | Eval awareness | Cost |" in summary
    assert summary.count("swarm.agents=") == 3


def test_stop_experiment_stops_supervisor_and_runs(
    runs_base, scenario, fakes, tmp_path, monkeypatch, no_docker
):
    monkeypatch.setenv("FAKE_RUN_SECONDS", "60")
    swarm("experiment", _exp_file(tmp_path, scenario, name="long"), "--dry-run", "--detach")
    wait_for(
        lambda: len([r for r in listing.all_rows(experiment="long") if r.status.state == "running"]) == 2
    )
    sup = experiment.read_supervisor("long")
    assert procs.is_alive(sup.pid, sup.pid_started)
    assert "long" in swarm("ps").output

    result = swarm("stop", "long", "--timeout", 20)
    assert result.exit_code == 0, result.output
    assert not procs.is_alive(sup.pid, sup.pid_started)
    rows = listing.all_rows(experiment="long")
    assert len(rows) == 2  # the third never started
    assert all(r.state == "stopped" for r in rows)
    sup = experiment.read_supervisor("long")
    assert sup.state == "stopped" and any("experiment stopped" in s for s in sup.skipped)


def test_experiment_without_per_run_cap_is_refused(runs_base, tmp_path, fakes):
    folder = make_scenario(tmp_path / "nocap", "name: nocap\n")
    result = swarm("experiment", _exp_file(tmp_path, folder), "--dry-run")
    assert result.exit_code == 1 and "needs its own max_cost" in result.output


# ---- cleanup ---------------------------------------------------------------------------


def test_cleanup_removes_only_resources_of_ended_runs(runs_base, monkeypatch):
    import os

    from swarmbench.runner import runs
    from swarmbench.status import StatusWriter
    from swarmbench.types import RunStatus

    live = runs.new_run_dir("live")
    me = {"pid": os.getpid(), "pid_started": procs.start_time(os.getpid())}
    StatusWriter(live, RunStatus(run_id=live.run_id, scenario="live", state="running", **me))
    old = runs.new_run_dir("old")
    StatusWriter(old, RunStatus(run_id=old.run_id, scenario="old", state="done"))
    found = [
        docker.Resource("container", "c-live", live.run_id, "p1"),
        docker.Resource("container", "c-old", old.run_id, "p2"),
        docker.Resource("volume", "v-old", old.run_id, "p2"),
        docker.Resource("container", "c-elsewhere", "2026-01-01T000000_from-another-checkout", "p3"),
    ]
    removed = []
    monkeypatch.setattr(docker, "labelled", lambda run_id=None: found)
    monkeypatch.setattr(docker, "remove", lambda rs: removed.extend(r.id for r in rs) or [])
    result = swarm("cleanup", "--yes")
    assert result.exit_code == 0, result.output
    assert removed == ["c-old", "v-old"]
    assert "Removed 2 of 2" in result.output and "Use --all" in result.output

    removed.clear()
    swarm("cleanup", "--yes", "--all")
    assert removed == ["c-old", "v-old", "c-elsewhere"]


def test_docker_label_listing_parses_output(monkeypatch):
    outputs = {
        "ps": "abc\trun-1\tproj-1\n",
        "volume": "vol-a\trun-1\tproj-1\n",
        "network": "",
    }
    calls = []

    def fake(*args, timeout=120):
        calls.append(args)
        out = outputs[args[0]] if "label=swarmbench.run" in " ".join(args) else ""
        if args[0] == "volume" and "label=com.docker.compose.project=proj-1" in args:
            out = "vol-a\t\tproj-1\nvol-b\t\tproj-1\n"
        return docker.subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(docker, "docker", fake)
    found = docker.labelled()
    assert [(r.kind, r.id, r.run_id) for r in found] == [
        ("container", "abc", "run-1"),
        ("volume", "vol-a", "run-1"),
        ("volume", "vol-b", "run-1"),  # found through the Compose project
    ]


# ---- judge, view, check, design ----------------------------------------------------------


def test_judge_command(runs_base, scenario, fakes, monkeypatch):
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    monkeypatch.setenv("FAKE_VERDICT", "severe")
    result = swarm("judge", run_dir.run_id)
    assert result.exit_code == 0, result.output
    assert "Verdict: severe" in result.output
    assert read_status(run_dir).verdict == "severe"


def test_judge_needs_logs(runs_base, scenario, fakes):
    from swarmbench.runner import runs

    s, _ = runs.resolve(scenario, {})
    run_dir = runs.prepare(s, runs.Launch(scenario_path=str(scenario)))
    result = swarm("judge", run_dir.run_id)
    assert result.exit_code == 1 and "no Inspect logs" in result.output


def test_view_commands(runs_base, scenario, fakes, monkeypatch):
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    calls = []
    monkeypatch.setattr(cli.subprocess, "call", lambda cmd: calls.append(cmd) or 0)
    assert swarm("view", run_dir.run_id).exit_code == 0
    assert swarm("view", run_dir.run_id, "--scout").exit_code == 0
    assert calls[0][1:] == ["view", "--log-dir", str(run_dir.logs)]
    assert calls[1][1:] == ["view", "--scans", str(run_dir.scans), "-T", str(run_dir.logs)]


def test_check_valid_scenario_with_fake_engine(runs_base, scenario, fakes):
    result = swarm("check", scenario)
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output and "Dry run passed" in result.output


def test_check_without_engine_validates_only(runs_base, scenario):
    # The real engine is still a stub on this branch.
    result = swarm("check", scenario)
    assert result.exit_code == 0, result.output
    assert "Validated only" in result.output


def test_check_reports_problems(runs_base, tmp_path):
    folder = make_scenario(
        tmp_path / "broken", "name: broken\nprompt: missing.md\nmax_cost: 3\nswarm: {model: x/y}\n"
    )
    result = swarm("check", folder)
    assert result.exit_code == 1
    assert "prompt file missing.md is missing" in result.output
    assert "no price for x/y" in result.output
    bad_yaml = make_scenario(tmp_path / "bad", "name: bad\nswarm: {agents: 0}\n")
    assert swarm("check", bad_yaml).exit_code == 1


def test_design_commands(runs_base, scenario, fakes, monkeypatch, tmp_path):
    from swarmbench import design

    calls = {}

    def new_scenario(idea, out_dir=None, model=None):
        calls["new"] = (idea, out_dir, model)
        return scenario

    def iterate_scenario(scenario_dir, run_dirs, out_dir=None, model=None):
        calls["iterate"] = (scenario_dir, [r.run_id for r in run_dirs])
        return scenario

    monkeypatch.setattr(design, "new_scenario", new_scenario)
    monkeypatch.setattr(design, "iterate_scenario", iterate_scenario)
    result = swarm("design", "new", "a swarm that audits itself", "--no-check")
    assert result.exit_code == 0, result.output
    assert calls["new"] == ("a swarm that audits itself", None, None)

    def no_review(idea, out_dir=None, model=None, critique=True):
        calls["critique"] = critique
        return scenario

    monkeypatch.setattr(design, "new_scenario", no_review)
    assert swarm("design", "new", "x", "--no-review", "--no-check").exit_code == 0
    assert calls["critique"] is False

    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    result = swarm("design", "iterate", scenario, "--from", run_dir.run_id)
    assert result.exit_code == 0, result.output
    assert calls["iterate"] == (scenario, [run_dir.run_id])
    assert "is valid" in result.output  # swarm check ran on the result


def test_design_not_available_yet(runs_base):
    result = swarm("design", "new", "idea")
    assert result.exit_code == 1 and "isn't available yet" in result.output


def test_launch_file_records_overrides(runs_base, scenario, fakes):
    swarm("run", scenario, "--dry-run", "--agents", 4, "--epochs", 2)
    (run_dir,) = list_runs(runs_base)
    launch = json.loads((run_dir.root / "launch.json").read_text())
    assert launch["overrides"] == {"swarm.agents": 4, "epochs": 2}


def test_design_errors_become_messages(runs_base, monkeypatch, scenario, fakes):
    from swarmbench import design

    class DesignError(Exception):
        pass

    def exists(idea, out_dir=None, model=None):
        raise FileExistsError(17, "exists", "scenarios/x")

    def invalid(idea, out_dir=None, model=None):
        raise DesignError("the model's draft failed validation twice")

    monkeypatch.setattr(design, "DesignError", DesignError, raising=False)
    monkeypatch.setattr(design, "new_scenario", exists)
    result = swarm("design", "new", "x")
    assert result.exit_code == 1 and "Not overwriting scenarios/x" in result.output
    monkeypatch.setattr(design, "new_scenario", invalid)
    result = swarm("design", "new", "x")
    assert result.exit_code == 1 and "failed validation twice" in result.output

    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    seen = {}

    def from_moment(run_dir, moment, out_dir=None, model=None, scenario_dir=None):
        seen.update(run=run_dir.run_id, moment=moment, scenario=scenario_dir)
        return scenario

    monkeypatch.setattr(design, "scenario_from_moment", from_moment, raising=False)
    result = swarm(
        "design",
        "moment",
        run_dir.run_id,
        "agent-2 rewrote the checker",
        "--scenario",
        scenario,
        "--no-check",
    )
    assert result.exit_code == 0, result.output
    assert seen == {"run": run_dir.run_id, "moment": "agent-2 rewrote the checker", "scenario": scenario}


def test_experiment_rejects_bad_max_parallel(runs_base, scenario, tmp_path):
    result = swarm("experiment", _exp_file(tmp_path, scenario), "--max-parallel", 0, "--dry-run")
    assert result.exit_code != 0
