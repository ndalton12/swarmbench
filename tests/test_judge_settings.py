"""Which judge, at what cap: Sonnet judges screens (and says so), and --judge-max-cost sets the
judge's cap everywhere it is counted. Mock and replay only; no model calls."""

from __future__ import annotations

import json

import yaml
from typer.testing import CliRunner

import swarmbench.judge as J
from swarmbench import cli, costs
from swarmbench.runner import experiment, runs, screen
from tests.test_screen import DULL, HOT, profiles, result, scenario_dir  # noqa: F401  (profiles: a fixture)

OPUS, SONNET = "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5"


# --- Sonnet judges screens -------------------------------------------------------------------------


def test_a_screen_is_judged_by_sonnet_unless_told_otherwise(tmp_path):
    path = scenario_dir(tmp_path, "s")
    opts = screen.with_screen_judge(screen.ScreenOptions(name="t", scenarios=[str(path)]))
    assert opts.judge_model == SONNET and "re-judge" in opts.judge_model_reason.lower()
    (p,) = screen.plan_runs(opts, opts.scenarios, 1)
    assert p.scenario.advanced.judge_model == SONNET
    assert p.scenario.advanced.extra["judge_model_reason"] == "screen"
    chosen = screen.with_screen_judge(screen.ScreenOptions(name="t", scenarios=[str(path)], judge_model=OPUS))
    assert chosen.judge_model == OPUS and chosen.judge_model_reason == ""
    (p,) = screen.plan_runs(chosen, chosen.scenarios, 1)
    assert p.scenario.advanced.judge_model == OPUS and "judge_model_reason" not in p.scenario.advanced.extra


def test_the_screen_says_why_at_launch_and_in_screen_yaml(tmp_path, runs_base, fakes, profiles):  # noqa: F811
    path = scenario_dir(tmp_path, "hot")
    out = CliRunner().invoke(cli.app, ["screen", str(path), "--name", "why", "--runs", "1", "--yes", "--attached"])
    assert out.exit_code == 0, out.output
    text = " ".join(out.output.split())
    assert f"Judge: {SONNET} judges screens to keep them cheap" in text and f"--judge-model {OPUS}" in text
    saved = yaml.safe_load((runs_base / "screens" / "why" / "screen.yaml").read_text())
    assert saved["judge_model"] == SONNET and "full assessment" in saved["judge_model_reason"]


def test_promote_suggests_rejudging_the_top_run_with_opus():
    sonnet_hot = {**HOT, "stats": {"judge_model": SONNET}}
    r = screen.assess(result("hot", sonnet_hot, DULL))
    assert r.label == "Promote"
    assert r.next_command.startswith(f"swarm judge run-hot-0 --judge-model {OPUS} && swarm run ")
    assert any("re-judge the top run with Opus" in why for why in r.reasons)
    opus_hot = {**HOT, "stats": {"judge_model": OPUS}}
    assert screen.assess(result("hot", opus_hot)).next_command.startswith("swarm run ")


def test_the_report_says_it_was_judged_by_sonnet_because_this_was_a_screen():
    from types import SimpleNamespace

    Settings = SimpleNamespace(advanced=SimpleNamespace(extra={"judge_model_reason": "screen"}))
    (note,) = J.judge_setting_notes(Settings, None, SONNET, forced=False)
    assert note.startswith(f"Judged by {SONNET} because this was a screen; re-judge with Opus")
    assert J.judge_setting_notes(Settings, None, OPUS, forced=False) == []  # re-judged with Opus: no note
    assert J.judge_setting_notes(Settings, None, SONNET, forced=True) == []  # --judge-model chose it


def test_a_screen_run_report_carries_the_note(tmp_path, monkeypatch):
    from tests.data.monitor_fp import make_recording as FP
    from tests.test_judge_two_pass import _default, _run

    rd = FP.make_run_dir(tmp_path)
    data = {"name": "rival-swarms", "prompt": "prompt.md", "swarm": {"agents": 2, "model": SONNET},
            "advanced": {"judge_model": SONNET, "extra": {"judge_model_reason": "screen"}}}
    (rd.root / "scenario.yaml").write_text(yaml.safe_dump(data))
    (rd.root / "prompt.md").write_text("Plan the routes.")
    monkeypatch.setattr(J, "default_cap", lambda settings: 100.0)
    r = _run(rd, _default)
    assert r.stats["judge_model"] == SONNET
    assert any(n.startswith(f"Judged by {SONNET} because this was a screen") for n in r.judge_notes)
    assert "because this was a screen; re-judge with Opus" in rd.report_md.read_text()


# --- --judge-max-cost ---------------------------------------------------------------------------------


def test_the_judge_cap_flag_is_counted_in_reservations_and_the_worst_case(tmp_path):
    path = scenario_dir(tmp_path, "c", max_cost=40)
    default, _ = runs.resolve(str(path), {})
    capped, _ = runs.resolve(str(path), {"advanced.judge_max_cost": 3.0})
    assert costs.judge_cap(default) == 10.0 and costs.judge_cap(capped) == 3.0
    assert costs.reservation(default) - costs.reservation(capped) == 7.0
    assert costs.estimate_max_cost(default).total - costs.estimate_max_cost(capped).total == 7.0
    # screens and experiments set it for every run
    opts = screen.ScreenOptions(name="t", scenarios=[str(path)], judge_max_cost=3.0)
    (p,) = screen.plan_runs(opts, opts.scenarios, 1)
    assert p.scenario.advanced.judge_max_cost == 3.0 and p.reserve == costs.reservation(p.scenario)
    exp = experiment.Experiment(name="e", scenarios=[str(path)], judge_max_cost=3.0, max_cost=100)
    (q,) = experiment.plan(exp)
    assert q.scenario.advanced.judge_max_cost == 3.0 and costs.judge_cap(q.scenario) == 3.0


def test_the_cli_takes_the_judge_cap(tmp_path, runs_base, fakes, profiles):  # noqa: F811
    path = scenario_dir(tmp_path, "hot")
    out = CliRunner().invoke(cli.app, ["run", str(path), "--dry-run", "--judge-max-cost", "3", "--attached"])
    assert out.exit_code == 0, out.output
    (run_dir,) = [r for r in runs_base.iterdir() if r.name.endswith("_hot")]
    launch = json.loads((run_dir / "launch.json").read_text())
    assert launch["overrides"]["advanced.judge_max_cost"] == 3.0  # the run's judge (and its reservation) use it
    bad = CliRunner().invoke(cli.app, ["run", str(path), "--dry-run", "--judge-max-cost", "0", "--attached"])
    assert bad.exit_code != 0
    exp_file = tmp_path / "e.yaml"
    exp_file.write_text(yaml.safe_dump({"name": "e", "scenarios": [str(path)]}))
    out = CliRunner().invoke(cli.app, ["experiment", str(exp_file), "--dry-run", "--judge-max-cost", "3", "--attached"])
    assert out.exit_code == 0, out.output
    saved = yaml.safe_load(next((runs_base / "experiments" / "e").glob("*.yaml")).read_text())
    assert saved["judge_max_cost"] == 3.0


def test_judging_again_with_a_cap_overrides_the_run_for_that_judging_only(tmp_path, monkeypatch):
    from tests.data.monitor_fp import make_recording as FP

    rd = FP.make_run_dir(tmp_path)
    monkeypatch.setattr(J, "_resolve_models", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no models")))
    (r,) = J.judge_run(rd, replay=FP.RECORDING, engine="two-pass", max_cost=7.5)
    assert r.stats["judge_cap_usd"] == 7.5
    assert any("set to $7.50 (--judge-max-cost)" in n for n in r.judge_notes)
    # with --resume too; the run's own setting is untouched
    (again,) = J.judge_run(rd, replay=FP.RECORDING, engine="two-pass", max_cost=6.0, resume=True)
    assert again.stats["judge_cap_usd"] == 6.0 and again.stats["chunks_resumed"] >= 1
    assert not (rd.root / "scenario.yaml").exists() or "judge_max_cost" not in (rd.root / "scenario.yaml").read_text()


def test_swarm_judge_passes_the_cap(tmp_path, runs_base, scenario, fakes, monkeypatch):
    from swarmbench.paths import list_runs

    assert CliRunner().invoke(cli.app, ["run", str(scenario), "--dry-run", "--attached"]).exit_code == 0
    (run_dir,) = list_runs(runs_base)
    seen = []
    monkeypatch.setattr(J, "judge_run", lambda rd, model=None, **kw: seen.append(kw) or [])
    out = CliRunner().invoke(cli.app, ["judge", run_dir.run_id, "--judge-max-cost", "4", "--resume"])
    assert out.exit_code == 0, out.output
    assert seen == [{"resume": True, "max_cost": 4.0}]


