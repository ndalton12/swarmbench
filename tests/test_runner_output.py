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
from tests.conftest import cli_args

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
    return runner.invoke(cli.app, cli_args(*args), input=input)


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


def test_the_verdict_printout_is_plain(runs_base, scenario, fakes, monkeypatch):
    """Verdict (marked when not fully assessed), the plain headline, what limits it, the summary and
    where the full report is; never the long technical coverage line or error text."""
    limit = "agent-2 crashed 12 minutes in, so its last 8 minutes weren't seen."
    monkeypatch.setenv("FAKE_PROFILES", json.dumps({"tiny": {"fully_assessed": False, "limits": [limit]}}))
    result = swarm("run", scenario, "--dry-run")
    assert "Verdict: minor (not fully assessed)" in result.output
    assert f"Limit: {limit}" in result.output
    assert "Coverage:" not in result.output
    assert "Full report: " in result.output and "report.md" in result.output


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
    monkeypatch.setattr(docker, "swarm_images", lambda **k: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda **k: set(used))
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


def test_only_swarmbench_images_are_ever_removed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        docker, "docker", lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", "")
    )
    for other in (
        "python:3.12-slim",
        "proof-conference-pilot:dab909d",
        "swarmbench-other:abc",
        "swarmbench-team",
    ):
        assert "not a swarmbench image" in docker.remove_image(other)
    assert calls == []
    for tag in (
        "swarmbench-team:abc",
        "swarmbench-base:abc",
        "swarmbench-scenario:abc",
        "swarmbench-scenario-lean:abc",
    ):
        assert docker.remove_image(tag) is None
    assert [c[1] for c in calls] == [
        "swarmbench-team:abc",
        "swarmbench-base:abc",
        "swarmbench-scenario:abc",
        "swarmbench-scenario-lean:abc",
    ]


def test_engine_and_cleanup_agree_on_image_names():
    from swarmbench.engine import image

    assert (image.BASE_REPO, image.SCENARIO_REPO, image.TEAM_REPO) == (
        docker.BASE_IMAGE_REPO,
        docker.SCENARIO_IMAGE_REPO,
        docker.TEAM_IMAGE_REPO,
    )


def layered(monkeypatch, images, layers, used=(), removed=None):
    """Fake Docker with these images (newest first) and their layer lists (by tag)."""
    by_id = {docker.short_id(i.id): tuple(layers[i.tag]) for i in images}
    monkeypatch.setattr(docker, "swarm_images", lambda **k: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda **k: set(used))
    monkeypatch.setattr(
        docker,
        "image_layers",
        lambda refs, **k: {docker.short_id(r): by_id[docker.short_id(r)] for r in refs},
    )
    if removed is not None:
        monkeypatch.setattr(docker, "remove_image", lambda tag: removed.append(tag))


def make_image(tag, minutes_old):
    now = datetime(2026, 10, 19, 13, 0, tzinfo=UTC)
    digest = f"{abs(hash(tag)):012x}"[:12]
    return docker.Image(tag, digest, now - timedelta(minutes=minutes_old))


def test_prune_base_and_scenario_images_not_under_a_kept_image(runs_base, monkeypatch):
    team_new = make_image("swarmbench-team:new", 1)
    scen_new = make_image("swarmbench-scenario:turf", 2)
    lean_new = make_image("swarmbench-scenario-lean:new", 3)
    base_new = make_image("swarmbench-base:new", 4)
    team_old = make_image("swarmbench-team:old", 50)
    scen_old = make_image("swarmbench-scenario:old", 60)
    lean_old = make_image("swarmbench-scenario-lean:old", 70)
    base_mid = make_image("swarmbench-base:mid", 80)  # under a container's image: kept
    base_old = make_image("swarmbench-base:old", 90)
    images = [team_new, scen_new, lean_new, base_new, team_old, scen_old, lean_old, base_mid, base_old]
    layers = {
        "swarmbench-base:new": ["b1", "b2"],
        "swarmbench-scenario:turf": ["b1", "b2", "s1"],
        "swarmbench-team:new": ["b1", "b2", "s1", "t1"],
        "swarmbench-scenario-lean:new": ["l1"],
        "swarmbench-team:old": ["o1", "o2", "o3"],
        "swarmbench-scenario:old": ["o1", "o2"],
        "swarmbench-scenario-lean:old": ["l0"],
        "swarmbench-base:mid": ["m1"],
        "swarmbench-base:old": ["o1"],
    }
    # a container of another repository (a pinned pilot image) sits on base:mid
    pinned = "sha256:" + "f" * 64
    layers_by_id = {docker.short_id(i.id): tuple(layers[i.tag]) for i in images} | {"f" * 12: ("m1", "p1")}
    monkeypatch.setattr(docker, "swarm_images", lambda **k: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda **k: {"proof-conference-pilot:x", pinned})
    monkeypatch.setattr(
        docker,
        "image_layers",
        lambda refs, **k: {docker.short_id(r): layers_by_id[docker.short_id(r)] for r in refs},
    )
    prune, note = control.images_to_prune(keep=1)
    # prebuilt stages, even old ones, are never pruned: another checkout may still need them
    assert [i.tag for i in prune] == ["swarmbench-team:old", "swarmbench-scenario:old", "swarmbench-base:old"]
    assert "9 swarmbench images (2 team, 3 base, 4 scenario); keeping 6" in note


def test_prune_leaves_base_and_scenario_images_alone_when_layers_are_unknown(runs_base, monkeypatch):
    images = [
        make_image("swarmbench-team:a", 1),
        make_image("swarmbench-base:a", 2),
        make_image("swarmbench-base:b", 3),
    ]
    monkeypatch.setattr(docker, "swarm_images", lambda **k: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda **k: set())
    monkeypatch.setattr(docker, "image_layers", lambda refs, **k: None)
    prune, note = control.images_to_prune(keep=1)
    assert prune == [] and "left alone" in note


def test_prune_leaves_base_and_scenario_images_alone_when_a_kept_image_has_unknown_layers(
    runs_base, monkeypatch
):
    images = [
        make_image("swarmbench-team:a", 1),
        make_image("swarmbench-base:a", 2),
        make_image("swarmbench-base:b", 3),
    ]
    known = {docker.short_id(images[1].id): ("x",), docker.short_id(images[2].id): ("y",)}  # team:a unknown
    monkeypatch.setattr(docker, "swarm_images", lambda **k: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda **k: set())
    monkeypatch.setattr(docker, "image_layers", lambda refs, **k: known)
    prune, note = control.images_to_prune(keep=1)
    assert prune == [] and "left alone" in note


def test_prune_nothing_when_containers_cant_be_listed(runs_base, monkeypatch):
    images = [make_image("swarmbench-team:a", 1), make_image("swarmbench-team:b", 2)]
    monkeypatch.setattr(docker, "swarm_images", lambda **k: images)
    monkeypatch.setattr(docker, "images_used_by_containers", lambda **k: None)
    prune, note = control.images_to_prune(keep=0)
    assert prune == [] and "couldn't list its containers" in note


def test_images_used_by_containers_inspects_them(monkeypatch):
    calls = []
    replies = {
        "ps": subprocess.CompletedProcess([], 0, "c1\nc2\n", ""),
        "container": subprocess.CompletedProcess(
            [], 0, "sha256:aaa\tswarmbench-team:x\nsha256:bbb\tsha256:bbb\n", ""
        ),
    }

    def fake(*args, timeout=120):
        calls.append(args)
        return replies[args[0]]

    monkeypatch.setattr(docker, "docker", fake)
    assert docker.images_used_by_containers() == {"sha256:aaa", "swarmbench-team:x", "sha256:bbb"}
    assert calls[0] == ("ps", "-aq", "--no-trunc") and calls[1][-2:] == ("c1", "c2")

    replies["ps"] = subprocess.CompletedProcess([], 0, "", "")
    assert docker.images_used_by_containers() == set()
    replies["ps"] = subprocess.CompletedProcess([], 1, "", "Cannot connect to the Docker daemon")
    assert docker.images_used_by_containers() is None
    replies["ps"] = subprocess.CompletedProcess([], 0, "c1\n", "")
    replies["container"] = subprocess.CompletedProcess([], 1, "", "No such container: c1")
    assert docker.images_used_by_containers() is None


def test_cleanup_lists_old_images_by_kind(runs_base, monkeypatch, no_docker):
    removed = []
    images = [
        make_image("swarmbench-team:a", 1),
        make_image("swarmbench-base:a", 2),
        make_image("swarmbench-base:b", 3),
    ]
    layered(
        monkeypatch,
        images,
        {"swarmbench-team:a": ["x", "t"], "swarmbench-base:a": ["x"], "swarmbench-base:b": ["y"]},
        removed=removed,
    )
    result = swarm("cleanup", "--yes", "--keep-images", 1)
    assert result.exit_code == 0, result.output
    assert removed == ["swarmbench-base:b"]
    assert "Old images: 1 swarmbench-base" in result.output and "Removed 1 of 1" in result.output


def test_swarm_images_parsing(monkeypatch):
    out = (
        "swarmbench-team\t80c92ce305a1\t787fed61f796\t2026-10-07 13:21:27 -0700 PDT\n"
        "swarmbench-base\t2baaa3f6b98f\t111111111111\t2026-10-07 13:00:00 -0700 PDT\n"
        "swarmbench-scenario-lean\tabc\t222222222222\t2026-10-07 12:00:00 -0700 PDT\n"
        "proof-conference-pilot\tdab909d\t333333333333\t2026-10-07 14:00:00 -0700 PDT\n"
        "swarmbench-scenario\t<none>\t444444444444\t2026-10-07 14:00:00 -0700 PDT\n"
    )
    monkeypatch.setattr(docker, "docker", lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))
    assert [i.tag for i in docker.swarm_images()] == [
        "swarmbench-team:80c92ce305a1",
        "swarmbench-base:2baaa3f6b98f",
        "swarmbench-scenario-lean:abc",
    ]
    assert [i.tag for i in docker.team_images()] == ["swarmbench-team:80c92ce305a1"]


def test_image_layers_parsing(monkeypatch):
    out = 'sha256:aaaaaaaaaaaa1111\t["sha256:l1","sha256:l2"]\nsha256:bbbbbbbbbbbb2222\tnull\n'
    monkeypatch.setattr(docker, "docker", lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))
    assert docker.image_layers(["x", "y"]) == {"aaaaaaaaaaaa": ("sha256:l1", "sha256:l2"), "bbbbbbbbbbbb": ()}
    monkeypatch.setattr(
        docker, "docker", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no such image")
    )
    assert docker.image_layers(["x"]) is None


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


def test_report_pager_shows_colours_in_less_and_plain_text_elsewhere():
    pager, styles = display.pager_for({"PATH": "/usr/bin"})
    assert pager.command == ["less"] and styles and pager.env["LESS"] == "-R"
    pager, styles = display.pager_for({"PAGER": "less -S", "LESS": "-X"})
    assert pager.command == ["less", "-S"] and styles and pager.env["LESS"] == "-X -R"
    pager, styles = display.pager_for({"PAGER": "more"})
    assert pager.command == ["more"] and not styles and "LESS" not in pager.env
    assert display.pager_for({"MANPAGER": "most", "PAGER": "less"})[0].command == ["most"]
