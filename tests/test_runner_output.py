"""Quiet output, run outcomes, short run names, image pruning and dead-run teardown.

Mock models and fake Docker only.
"""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from rich.console import Console
from typer.testing import CliRunner

from swarmbench import cli, engine
from swarmbench.paths import list_runs
from swarmbench.runner import control, display, docker, experiment, procs, runs
from swarmbench.status import StatusWriter, read_status
from swarmbench.types import CostSummary, RunStatus
from tests import fake_launcher

runner = CliRunner()


@pytest.fixture(autouse=True)
def plain_output(monkeypatch):
    out = Console(width=250, force_terminal=False, no_color=True, highlight=False)
    err = Console(width=250, force_terminal=False, no_color=True, highlight=False, stderr=True)
    for module in (cli, display):
        monkeypatch.setattr(module, "console", out)
        monkeypatch.setattr(module, "err", err)


@pytest.fixture
def no_docker(monkeypatch):
    calls = []

    def fake(*args, timeout=120):
        calls.append(args)
        return subprocess.CompletedProcess(["docker", *args], 0, "", "")

    monkeypatch.setattr(docker, "docker", fake)
    return calls


def swarm(*args, input=None):
    return runner.invoke(cli.app, [str(a) for a in args], input=input)


# ---- quiet output ----------------------------------------------------------------------


def noisy_engine(scenario, run_dir, status, dry_run=False):
    """Writes the kind of chatter Docker, Inspect and Scout produce, at every level."""
    print("Indexing: file:///somewhere scan: swarmbench-judge", flush=True)
    os.write(1, b"scanning:   0% (0/12)\n")
    os.write(2, b'time="2026-10-07T13:23:19-07:00" level=warning msg="No services to build"\n')
    subprocess.run(["sh", "-c", "echo compose-chatter; echo compose-warning >&2"], check=True)
    return fake_launcher.write_log(run_dir)


def test_run_sends_library_chatter_to_the_log(runs_base, scenario, fakes, monkeypatch, capfd):
    monkeypatch.setattr(engine, "run_scenario", noisy_engine)
    result = swarm("run", scenario, "--dry-run")
    assert result.exit_code == 0, result.output
    captured = capfd.readouterr()
    shown = result.output + captured.out + captured.err
    for noise in ("Indexing", "scanning:", "No services to build", "compose-chatter", "compose-warning"):
        assert noise not in shown
    assert "Swarm running..." in result.output and "Judging..." in result.output
    assert "Verdict: minor" in result.output
    (run_dir,) = list_runs(runs_base)
    log = run_dir.run_log.read_text()
    for noise in ("Indexing", "scanning:", "No services to build", "compose-chatter", "compose-warning"):
        assert noise in log


def test_verbose_shows_the_chatter(runs_base, scenario, fakes, monkeypatch, capfd):
    monkeypatch.setattr(engine, "run_scenario", noisy_engine)
    result = swarm("run", scenario, "--dry-run", "--verbose")
    assert result.exit_code == 0, result.output
    captured = capfd.readouterr()
    assert "compose-chatter" in captured.out and "No services to build" in captured.err


def test_check_is_quiet_too(runs_base, scenario, fakes, monkeypatch, capfd):
    monkeypatch.setattr(engine, "run_scenario", noisy_engine)
    result = swarm("check", scenario)
    assert result.exit_code == 0, result.output
    captured = capfd.readouterr()
    assert "compose-chatter" not in result.output + captured.out + captured.err


# ---- outcomes --------------------------------------------------------------------------


def test_agent_errors_make_the_run_failed_but_still_judged(runs_base, scenario, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_OUTCOME", "agent_errors")
    result = swarm("run", scenario, "--dry-run")
    assert result.exit_code == 1
    assert "Verdict: minor" in result.output  # the judge still ran
    assert "Problem: agent-2 crashed: out of memory" in result.output
    (run_dir,) = list_runs(runs_base)
    status = read_status(run_dir)
    assert status.state == "failed" and status.verdict == "minor"
    listed = swarm("list").output
    assert "failed" in listed and "Problem" in listed and "agent-2 crashed" in listed


def test_sample_error_makes_the_run_failed(runs_base, scenario, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_SAMPLE_ERROR", "1")
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    status = read_status(run_dir)
    assert status.state == "failed" and "container exploded" in status.error


def test_monitor_stop_is_done_with_a_note(runs_base, scenario, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_OUTCOME", "monitor_stop")
    result = swarm("run", scenario, "--dry-run")
    assert result.exit_code == 0, result.output
    assert "Note: stopped early by the monitor" in result.output
    (run_dir,) = list_runs(runs_base)
    assert read_status(run_dir).state == "done"


def test_clean_outcome_is_done(runs_base, scenario, fakes, monkeypatch):
    monkeypatch.setenv("FAKE_OUTCOME", "ok")
    assert swarm("run", scenario, "--dry-run").exit_code == 0
    (run_dir,) = list_runs(runs_base)
    status = read_status(run_dir)
    assert status.state == "done" and status.error is None


def test_no_log_is_a_failure(runs_base, scenario, fakes, monkeypatch):
    monkeypatch.setattr(engine, "run_scenario", lambda *a, **k: [])
    result = swarm("run", scenario, "--dry-run")
    assert result.exit_code == 1 and "without writing an Inspect log" in result.output


# ---- run names ---------------------------------------------------------------------------


def test_short_names():
    assert runs.short_id("2026-10-07T132117_rival-swarms") == "10-07 13:21 rival-swarms"
    assert runs.short_id("2026-10-07T132117_rival-swarms-2") == "10-07 13:21 rival-swarms-2"
    assert runs.short_id("something-else") == "something-else"


def test_commands_accept_the_short_name(runs_base, scenario, fakes):
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    short = runs.short_id(run_dir.run_id)
    assert runs.find_run(short).root == run_dir.root
    assert runs.find_run(run_dir.run_id).root == run_dir.root
    assert runs.find_run(run_dir.run_id[5:]).root == run_dir.root  # any unique part
    assert swarm("view", short, "--help").exit_code == 0


def test_run_names_never_wrap_in_narrow_tables(runs_base, scenario, fakes, monkeypatch):
    narrow = Console(width=80, force_terminal=False, no_color=True, highlight=False)
    monkeypatch.setattr(cli, "console", narrow)
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    status = read_status(run_dir)
    StatusWriter(run_dir, status.model_copy(update={"headline": "A very long headline " * 10}))
    out = swarm("list").output
    assert runs.short_id(run_dir.run_id) in out
    assert "…" in out  # the headline is cut short instead of wrapping


# ---- image pruning ---------------------------------------------------------------------


def fake_images(monkeypatch, count, used=(), removed=None):
    now = datetime(2026, 10, 7, 13, 0, tzinfo=UTC)
    images = [
        docker.Image(f"swarmbench-team:{i:012x}", f"id{i:010d}", now - timedelta(minutes=i))
        for i in range(count)
    ]
    monkeypatch.setattr(docker, "team_images", lambda: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda: set(used))
    if removed is not None:
        monkeypatch.setattr(docker, "remove_image", lambda tag: removed.append(tag))
    return images


def test_prune_keeps_newest_and_images_in_use(runs_base, monkeypatch):
    # Image 8 is used by a container; image 7 by a live run in this runs folder.
    images = fake_images(monkeypatch, 10, used={images_tag(8)})
    live = runs.new_run_dir("live")
    me = {"pid": os.getpid(), "pid_started": procs.start_time(os.getpid())}
    StatusWriter(live, RunStatus(run_id=live.run_id, scenario="live", state="running", **me))
    live.provenance.write_text(json.dumps({"images": [{"tag": images_tag(7), "id": "x"}]}))
    prune, note = control.images_to_prune(keep=5)
    assert [i.tag for i in prune] == [images[5].tag, images[6].tag, images[9].tag]
    assert "keeping 7" in note


def images_tag(i):
    return f"swarmbench-team:{i:012x}"


def test_prune_waits_while_a_run_is_building(runs_base, monkeypatch):
    fake_images(monkeypatch, 10)
    starting = runs.new_run_dir("starting")
    StatusWriter(starting, RunStatus(run_id=starting.run_id, scenario="s", state="starting"))
    prune, note = control.images_to_prune(keep=2)
    assert prune == [] and "may be building images" in note


def test_cleanup_prunes_images(runs_base, monkeypatch, no_docker):
    removed = []
    fake_images(monkeypatch, 8, removed=removed)
    result = swarm("cleanup", "--yes", "--keep-images", 6)
    assert result.exit_code == 0, result.output
    assert removed == [images_tag(6), images_tag(7)]
    assert "Removed 2 of 2" in result.output

    removed.clear()
    result = swarm("cleanup", "--yes", "--no-images")
    assert removed == [] and "Nothing to remove" in result.output


def test_only_team_images_are_ever_removed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        docker, "docker", lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", "")
    )
    assert "not a swarmbench-team image" in docker.remove_image("python:3.12-slim")
    assert "not a swarmbench-team image" in docker.remove_image("swarmbench-base:abc")
    assert calls == []
    assert docker.remove_image("swarmbench-team:abc") is None
    assert calls == [("rmi", "swarmbench-team:abc")]


def test_team_images_parsing(monkeypatch):
    out = (
        "swarmbench-team\t80c92ce305a1\t787fed61f796\t2026-10-07 13:21:27 -0700 PDT\n"
        "swarmbench-team\t<none>\t111111111111\t2026-10-07 13:00:00 -0700 PDT\n"
        "swarmbench-team\t55cea37c7c00\t8d81315405fd\t2026-10-07 13:23:18 -0700 PDT\n"
    )
    monkeypatch.setattr(docker, "docker", lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))
    assert [i.tag for i in docker.team_images()] == [
        "swarmbench-team:55cea37c7c00",
        "swarmbench-team:80c92ce305a1",
    ]


# ---- dead runs and settled costs ---------------------------------------------------------


def test_supervisor_tears_down_a_dead_run_and_settles_its_logged_cost(
    runs_base, scenario, monkeypatch, no_docker
):
    from inspect_ai.model import ModelCost, ModelInfo, set_model_info

    from swarmbench import costs

    exp = experiment.Experiment(name="dead", scenarios=[str(scenario)], max_parallel=1, max_cost=100)
    planned = experiment.plan(exp)
    messages = []

    def start(run_dir):
        status = read_status(run_dir)
        # Three epochs logged, but the live status only covered the last one, then the process died.
        set_model_info(
            "mockllm/model",
            ModelInfo(cost=ModelCost(input=0, output=1e7, input_cache_write=0, input_cache_read=0)),
        )
        fake_launcher.write_log(run_dir, epochs=3)
        StatusWriter(
            run_dir,
            status.model_copy(
                update={
                    "state": "running",
                    "pid": 999_999_99,
                    "pid_started": 1.0,
                    "swarm_cost": CostSummary(usd=0.01),
                    "compose_project": "proj-dead",
                }
            ),
        )
        return 999_999_99, 1.0

    sup = experiment.Supervisor(exp, planned, base=runs_base, poll=0, start_run=start, say=messages.append)
    (experiment.experiment_dir("dead", runs_base)).mkdir(parents=True)
    try:
        sup.run(experiment.SupervisorState(name="dead"))
        logged = costs.eval_logs_cost(list_runs(runs_base)[0].eval_logs()).usd
    finally:
        costs.model_cost_config()
    assert logged > 2.5  # 3 epochs of mock output at $10 per token
    # Charged at least its reservation ($2 cap + $1 judge) and at least what the logs show.
    assert sup.spent == pytest.approx(max(logged, planned[0].reserve))
    (run_dir,) = list_runs(runs_base)
    assert read_status(run_dir).state == "failed"
    assert (
        "compose",
        "-p",
        "proj-dead",
        "down",
        "--volumes",
        "--remove-orphans",
        "--timeout",
        "10",
    ) in no_docker
    assert any("died" in m for m in messages)
