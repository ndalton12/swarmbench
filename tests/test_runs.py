"""One run with a fake engine and judge: overrides, status, verdicts, failures."""

import json

import pytest

from swarmbench import engine, judge
from swarmbench.runner import runs
from swarmbench.status import read_status
from tests.conftest import make_scenario

TWO_TEAMS = (
    "name: rivals\nswarm: {agents: 2, model: anthropic/claude-sonnet-5-5}\n"
    "teams: [{name: red, agents: 5, model: anthropic/claude-opus-5-5}, {name: blue}]\n"
)


def test_flags_beat_team_settings(tmp_path):
    folder = make_scenario(tmp_path, TWO_TEAMS)
    # Without flags: team settings beat the swarm block.
    s, _ = runs.resolve(folder, {})
    red, blue = s.resolved_teams()
    assert (red.agents, red.model) == (5, "anthropic/claude-opus-5-5")
    assert (blue.agents, blue.model) == (2, "anthropic/claude-sonnet-5-5")

    # Flags beat team settings, for every team.
    s, overrides = runs.resolve(folder, {"swarm.agents": 3, "swarm.model": "mockllm/model", "epochs": None})
    assert all(t.agents == 3 and t.model == "mockllm/model" for t in s.resolved_teams())
    assert "epochs" not in overrides
    # Settings a flag doesn't touch stay with the team.
    s, _ = runs.resolve(folder, {"swarm.effort": "high"})
    assert s.resolved_teams()[0].agents == 5


def test_flags_on_single_swarm(tmp_path):
    folder = make_scenario(tmp_path)
    s, overrides = runs.resolve(folder, {"swarm.token_budget": "1M", "max_cost": 7.5, "epochs": 2})
    assert s.swarm.token_budget == 1_000_000 and s.max_cost == 7.5 and s.epochs == 2
    assert "teams" not in overrides


def test_new_run_dirs_in_the_same_second_are_distinct(tmp_path):
    a = runs.new_run_dir("tiny", tmp_path)
    b = runs.new_run_dir("tiny", tmp_path)
    c = runs.new_run_dir("tiny", tmp_path)
    assert len({a.root, b.root, c.root}) == 3
    assert all(d.logs.is_dir() for d in (a, b, c))


def _prepared(scenario, runs_base, **launch):
    s, overrides = runs.resolve(scenario, {})
    return runs.prepare(s, runs.Launch(scenario_path=str(scenario), overrides=overrides, **launch))


def test_execute_success(runs_base, scenario, fakes):
    run_dir = _prepared(scenario, runs_base, dry_run=True)
    assert read_status(run_dir).state == "starting"
    assert json.loads(runs.launch_file(run_dir).read_text())["dry_run"] is True

    status = runs.execute(run_dir)
    assert status.state == "done" and status.finished is not None
    assert status.verdict == "minor" and status.headline == "Fake headline (minor)"
    # The judge's own write to status.json (judge cost) survives our final write.
    on_disk = read_status(run_dir)
    assert on_disk.judge_cost.usd == 0.25 and on_disk.swarm_cost.usd == 1.0
    assert on_disk.state == "done" and on_disk.agents_total == 2
    assert runs.read_reports(run_dir)[0].verdict == "minor"


def test_dry_run_judge_uses_mock_model(runs_base, scenario, fakes, monkeypatch):
    seen = {}

    def judge_run(run_dir, model=None):
        seen["model"] = model
        return []

    monkeypatch.setattr(judge, "judge_run", judge_run)
    runs.execute(_prepared(scenario, runs_base, dry_run=True))
    assert seen["model"] == "mockllm/model"


def test_execute_failure_is_recorded(runs_base, scenario, fakes, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("container would not start")

    monkeypatch.setattr(engine, "run_scenario", boom)
    status = runs.execute(_prepared(scenario, runs_base))
    assert status.state == "failed" and "container would not start" in status.error


def test_execute_without_engine_says_not_implemented(runs_base, scenario, monkeypatch):
    def not_yet(*a, **k):
        raise NotImplementedError

    monkeypatch.setattr(engine, "run_scenario", not_yet)
    status = runs.execute(_prepared(scenario, runs_base))
    assert status.state == "failed" and status.error.startswith("not implemented yet")


def test_stop_skips_judging(runs_base, scenario, fakes, monkeypatch):
    def interrupted(*a, **k):
        raise KeyboardInterrupt

    def judge_run(*a, **k):
        pytest.fail("judge should not run after a stop")

    monkeypatch.setattr(engine, "run_scenario", interrupted)
    monkeypatch.setattr(judge, "judge_run", judge_run)
    status = runs.execute(_prepared(scenario, runs_base))
    assert status.state == "stopped"


def test_worst_verdict():
    from swarmbench.types import JudgeReport

    def r(v):
        return JudgeReport(run_id="x", scenario="s", verdict=v, headline=v, summary="")

    assert runs.worst_verdict([r("minor"), r("severe"), r("none")]) == "severe"
    assert runs.worst_verdict([]) is None


def test_find_run(runs_base, scenario, fakes):
    run_dir = _prepared(scenario, runs_base)
    assert runs.find_run(run_dir.run_id).root == run_dir.root
    assert runs.find_run(str(run_dir.root)).root == run_dir.root
    assert runs.find_run(run_dir.run_id[:15]).root == run_dir.root
    with pytest.raises(FileNotFoundError):
        runs.find_run("nope")


def test_stop_file_skips_judging_even_if_the_signal_was_swallowed(runs_base, scenario, fakes, monkeypatch):
    def judge_run(*a, **k):
        pytest.fail("judge should not run after a stop")

    run_dir = _prepared(scenario, runs_base)
    runs.request_stop(run_dir)  # as swarm stop does, before signalling
    monkeypatch.setattr(judge, "judge_run", judge_run)
    assert runs.execute(run_dir).state == "stopped"


def test_judge_cost_survives_a_failing_judge(runs_base, scenario, fakes, monkeypatch):
    from swarmbench.types import CostSummary

    def judge_run(run_dir, model=None):
        status = read_status(run_dir)
        status.judge_cost = CostSummary(usd=0.75)
        run_dir.status.write_text(status.model_dump_json())
        raise RuntimeError("scanner crashed")

    monkeypatch.setattr(judge, "judge_run", judge_run)
    run_dir = _prepared(scenario, runs_base)
    status = runs.execute(run_dir)
    assert status.state == "failed" and "scanner crashed" in status.error
    assert read_status(run_dir).judge_cost.usd == 0.75


def test_stop_before_the_worker_starts(runs_base, scenario, fakes):
    from swarmbench.runner import control

    run_dir = _prepared(scenario, runs_base)  # launched but its worker hasn't recorded a pid
    outcome = control.stop_runs([run_dir], grace=0.3, timeout=0.1, say=lambda m: None)
    assert outcome == {run_dir.run_id: "stop requested"}
    assert runs.stop_file(run_dir).exists()
    assert runs.execute(run_dir).state == "stopped"  # the worker sees it as soon as it starts
