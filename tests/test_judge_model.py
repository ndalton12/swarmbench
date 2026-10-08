"""--judge-model and the judge-is-also-under-test note. Fake engine and judge only."""

import json

import pytest
from rich.console import Console
from typer.testing import CliRunner

from swarmbench import cli, costs, engine, judge
from swarmbench.config import load_scenario
from swarmbench.paths import list_runs
from swarmbench.runner import display
from tests import fake_launcher
from tests.conftest import make_scenario

runner = CliRunner()
SONNET = "anthropic/claude-sonnet-5-5"
OPUS = "anthropic/claude-opus-5-5"
NOTE = "is also a model under test; its assessments may be biased toward its own behavior."


@pytest.fixture(autouse=True)
def plain_output(monkeypatch):
    out = Console(width=250, force_terminal=False, no_color=True, highlight=False)
    err = Console(width=250, force_terminal=False, no_color=True, highlight=False, stderr=True)
    for module in (cli, display):
        monkeypatch.setattr(module, "console", out)
        monkeypatch.setattr(module, "err", err)


@pytest.fixture
def opus_judge(monkeypatch):
    """The judge's planned default: Opus 5.5 for every role."""
    monkeypatch.setattr(judge, "DEFAULT_JUDGE_MODELS", [OPUS], raising=False)


def swarm(*args, input=None):
    return runner.invoke(cli.app, [str(a) for a in args], input=input)


def test_judge_models_resolution(tmp_path, opus_judge):
    s = load_scenario(make_scenario(tmp_path / "a", f"name: a\nswarm: {{model: {OPUS}}}\n"))
    assert costs.judge_models(s) == [OPUS] and costs.judge_overlap(s) == [OPUS]
    s = load_scenario(make_scenario(tmp_path / "b", f"name: b\nswarm: {{model: {SONNET}}}\n"))
    assert costs.judge_overlap(s) == []
    s = load_scenario(
        make_scenario(
            tmp_path / "c", f"name: c\nswarm: {{model: {SONNET}}}\nadvanced: {{judge_model: {SONNET}}}\n"
        )
    )
    assert costs.judge_models(s) == [SONNET] and costs.judge_overlap(s) == [SONNET]


def test_estimate_uses_the_judge_models_prices(tmp_path, opus_judge):
    s = load_scenario(
        make_scenario(tmp_path / "a", f"name: a\nswarm: {{model: {SONNET}, agents: 4}}\nmax_cost: 40\n")
    )
    e = costs.estimate_max_cost(s)
    assert e.judge_models == [OPUS] and e.judge_per_epoch == 10 and e.total == pytest.approx(50)
    unpriced = load_scenario(
        make_scenario(tmp_path / "b", "name: b\nmax_cost: 40\nadvanced: {judge_model: openai/gpt-5.5}\n")
    )
    e = costs.estimate_max_cost(unpriced)
    assert e.judge_per_epoch is None and e.total is None and "openai/gpt-5.5" in e.unpriced_models


def test_run_warns_when_the_judge_is_under_test(runs_base, tmp_path, fakes, opus_judge, monkeypatch):
    monkeypatch.setenv("SWARMBENCH_CONFIRM_ABOVE", "1")
    folder = make_scenario(tmp_path / "s", f"name: s\nswarm: {{model: {SONNET}}}\nmax_cost: 40\n")
    out = swarm("run", folder, input="n\n").output
    assert NOTE not in out  # Sonnet agents, Opus judge
    assert "Judge: anthropic/claude-opus-5-5" in out
    assert "Worst case: $50.00 = ($40.00 swarm cap + $10.00 judge cap) x 1 epoch" in out
    assert "the judge stops itself at $10.00: at most $50.00 in all. Launch?" in out

    out = swarm("run", folder, "--model", OPUS, input="n\n").output
    assert f"Note: the judge ({OPUS}) {NOTE}" in out
    assert out.index("Note:") < out.index("Launch?")  # before the cost prompt

    out = swarm("run", folder, "--judge-model", SONNET, input="n\n").output
    assert f"Note: the judge ({SONNET}) {NOTE}" in out

    assert NOTE not in swarm("run", folder, "--model", OPUS, "--dry-run").output  # the mock judge


def test_judge_model_flag_becomes_advanced_judge_model(runs_base, tmp_path, fakes, monkeypatch):
    seen = {}

    def run_scenario(scenario, run_dir, status, dry_run=False):
        seen["judge_model"] = scenario.advanced.judge_model
        return fake_launcher.write_log(run_dir)

    monkeypatch.setattr(engine, "run_scenario", run_scenario)
    folder = make_scenario(tmp_path / "s")
    assert swarm("run", folder, "--judge-model", OPUS, "--yes").exit_code == 0
    assert seen["judge_model"] == OPUS
    (run_dir,) = list_runs(runs_base)
    assert json.loads((run_dir.root / "launch.json").read_text())["overrides"]["advanced.judge_model"] == OPUS


def test_judge_command_takes_judge_model(runs_base, scenario, fakes, monkeypatch):
    swarm("run", scenario, "--dry-run")
    (run_dir,) = list_runs(runs_base)
    seen = []
    monkeypatch.setattr(judge, "judge_run", lambda rd, model=None: seen.append(model) or [])
    assert swarm("judge", run_dir.run_id, "--judge-model", OPUS).exit_code == 0
    assert swarm("judge", run_dir.run_id, "--model", SONNET).exit_code == 0
    assert seen == [OPUS, SONNET]


def test_experiment_warns_only_for_overlapping_combinations(runs_base, tmp_path, fakes, opus_judge):
    folder = make_scenario(tmp_path / "s", f"name: s\nswarm: {{model: {SONNET}}}\nmax_cost: 4\n")
    f = tmp_path / "e.yaml"
    f.write_text(f"name: sweep\nscenarios: [{folder}]\nvary:\n  swarm.model: [{SONNET}, {OPUS}]\n")
    out = swarm("experiment", f, input="n\n").output
    assert f"Note for swarm.model={OPUS}: the judge ({OPUS}) {NOTE}" in out
    assert f"swarm.model={SONNET}:" not in out


def test_experiment_judge_model_applies_to_every_run(tmp_path):
    from swarmbench.runner import experiment

    folder = make_scenario(tmp_path / "s")
    exp = experiment.Experiment(name="x", scenarios=[str(folder)], judge_model=OPUS)
    (p,) = experiment.plan(exp)
    assert p.scenario.advanced.judge_model == OPUS and p.overrides["advanced.judge_model"] == OPUS


def test_screen_passes_and_warns(runs_base, tmp_path, fakes, monkeypatch):
    from swarmbench.runner import screen

    folder = make_scenario(tmp_path / "s", f"name: s\nswarm: {{model: {SONNET}, agents: 6}}\nmax_cost: 40\n")
    opts = screen.ScreenOptions(name="t", scenarios=[str(folder)], judge_model=SONNET)
    (p,) = screen.plan_runs(opts, opts.scenarios, 1)
    assert p.scenario.advanced.judge_model == SONNET
    out = swarm("screen", folder, "--judge-model", SONNET, "--runs", 1, "--name", "j", input="n\n").output
    assert f"Note: the judge ({SONNET}) {NOTE}" in out
