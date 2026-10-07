"""Experiments: the grid, cost reservations, and the supervisor's budget and parallelism."""

import os

import pytest

from swarmbench.runner import experiment, listing, procs, runs
from swarmbench.status import StatusWriter, read_status
from swarmbench.types import CostSummary
from tests.conftest import make_scenario

SONNET = "anthropic/claude-sonnet-5-5"
OPUS = "anthropic/claude-opus-5-5"


def write_exp(tmp_path, text):
    f = tmp_path / "exp.yaml"
    f.write_text(text)
    return f


def test_plan_expands_the_grid(tmp_path, scenario):
    f = write_exp(
        tmp_path,
        f"name: sweep\nscenarios: [{scenario}]\n"
        f"vary:\n  swarm.model: [{SONNET}, {OPUS}]\n  swarm.agents: [2, 6]\n"
        "epochs: 3\nmax_parallel: 2\nmax_cost: 500\n",
    )
    exp = experiment.load_experiment(f)
    planned = experiment.plan(exp)
    assert len(planned) == 4
    assert planned[0].settings == {"swarm.model": SONNET, "swarm.agents": 2}
    assert planned[3].scenario.swarm.model == OPUS and planned[3].scenario.swarm.agents == 6
    assert all(p.scenario.epochs == 3 for p in planned)
    # Each reserves (max_cost + judge allowance) x epochs = (2 + 1) x 3.
    assert all(p.reserve == pytest.approx(9) for p in planned)


def test_plan_names_scenario_when_several(tmp_path):
    a = make_scenario(tmp_path / "a")
    b = make_scenario(tmp_path / "b", "name: other\n")
    exp = experiment.Experiment(name="two", scenarios=[str(a), str(b)])
    planned = experiment.plan(exp)
    assert [p.settings for p in planned] == [{"scenario": "a"}, {"scenario": "b"}]


def test_plan_requires_per_run_caps_with_a_budget(tmp_path):
    folder = make_scenario(tmp_path / "s", "name: nocap\n")
    exp = experiment.Experiment(name="x", scenarios=[str(folder)], max_cost=100)
    with pytest.raises(ValueError, match="needs its own max_cost"):
        experiment.plan(exp)
    # Varying max_cost supplies the cap.
    exp.vary = {"max_cost": [5, 10]}
    assert [p.reserve for p in experiment.plan(exp)] == [
        pytest.approx(6.25),
        pytest.approx(12.5),
    ]  # 5 + 25%, 10 + 25%


def test_plan_needs_prices_with_a_budget(tmp_path, scenario):
    exp = experiment.Experiment(
        name="x", scenarios=[str(scenario)], vary={"swarm.model": ["openai/gpt-5.5"]}, max_cost=100
    )
    with pytest.raises(ValueError, match="no price for openai/gpt-5.5"):
        experiment.plan(exp)


def test_plan_rejects_a_run_bigger_than_the_budget(tmp_path, scenario):
    exp = experiment.Experiment(name="x", scenarios=[str(scenario)], max_cost=1)
    with pytest.raises(ValueError, match="more than the whole budget"):
        experiment.plan(exp)


def test_plan_reports_bad_settings(tmp_path, scenario):
    exp = experiment.Experiment(name="x", scenarios=[str(scenario)], vary={"swarm.harness": ["bogus"]})
    with pytest.raises(ValueError, match="harness"):
        experiment.plan(exp)


# ---- supervisor, with fake runs that finish when the supervisor "sleeps" ---------------


class FakeRuns:
    """Starts fake runs (status files only) and finishes the oldest one on every poll."""

    def __init__(self, cost: float):
        self.cost = cost
        self.running = []
        self.max_seen = 0
        self.committed_seen = []

    def start(self, run_dir):
        status = read_status(run_dir)
        StatusWriter(
            run_dir,
            status.model_copy(
                update={"state": "running", "pid": os.getpid(), "pid_started": procs.start_time(os.getpid())}
            ),
        )
        self.running.append(run_dir)
        self.max_seen = max(self.max_seen, len(self.running))
        return os.getpid(), procs.start_time(os.getpid())

    def tick(self, sup):
        self.committed_seen.append(sup.committed())
        if self.running:
            rd = self.running.pop(0)
            status = read_status(rd)
            StatusWriter(
                rd,
                status.model_copy(
                    update={"state": "done", "verdict": "none", "swarm_cost": CostSummary(usd=self.cost)}
                ),
            )


def run_supervisor(monkeypatch, exp, fake, base):
    planned = experiment.plan(exp)
    messages = []
    sup = experiment.Supervisor(exp, planned, base=base, poll=0, start_run=fake.start, say=messages.append)
    monkeypatch.setattr(experiment.time, "sleep", lambda s: fake.tick(sup))
    experiment_dir = experiment.experiment_dir(exp.name, base)
    experiment_dir.mkdir(parents=True)
    state = sup.run(experiment.SupervisorState(name=exp.name))
    return sup, state, messages


def test_supervisor_respects_max_parallel_and_budget(runs_base, scenario, monkeypatch):
    # 6 runs reserving $3 each; budget $10 allows 3 at once, max_parallel 2 allows 2.
    exp = experiment.Experiment(
        name="grid",
        scenarios=[str(scenario)],
        vary={"swarm.agents": [1, 2, 3, 4, 5, 6]},
        max_parallel=2,
        max_cost=10,
    )
    fake = FakeRuns(cost=0.5)
    sup, state, _ = run_supervisor(monkeypatch, exp, fake, runs_base)
    assert state.state == "done" and len(state.runs) == 6 and not state.skipped
    assert fake.max_seen == 2
    assert max(fake.committed_seen) <= 10
    assert sup.spent == pytest.approx(6 * 0.5)
    rows = listing.all_rows(runs_base, experiment="grid")
    assert len(rows) == 6 and {r.status.settings["swarm.agents"] for r in rows} == {1, 2, 3, 4, 5, 6}


def test_supervisor_skips_runs_that_no_longer_fit(runs_base, scenario, monkeypatch):
    # Each run reserves $3; the first costs more than expected ($8), so only $2 is left.
    exp = experiment.Experiment(
        name="tight", scenarios=[str(scenario)], vary={"swarm.agents": [1, 2, 3]}, max_parallel=1, max_cost=10
    )
    fake = FakeRuns(cost=8)
    _, state, messages = run_supervisor(monkeypatch, exp, fake, runs_base)
    assert len(state.runs) == 1
    assert len(state.skipped) == 2 and "only $2.00 left" in state.skipped[0]
    assert any(m.startswith("skipped") for m in messages)


def test_supervisor_without_budget_runs_everything(runs_base, scenario, monkeypatch):
    exp = experiment.Experiment(
        name="free", scenarios=[str(scenario)], vary={"swarm.agents": [1, 2, 3]}, max_parallel=3
    )
    fake = FakeRuns(cost=100)
    _, state, _ = run_supervisor(monkeypatch, exp, fake, runs_base)
    assert len(state.runs) == 3 and fake.max_seen == 3


def test_unknown_cost_keeps_the_reservation(runs_base, scenario, monkeypatch):
    exp = experiment.Experiment(
        name="unknown",
        scenarios=[str(scenario)],
        vary={"swarm.agents": [1, 2, 3, 4]},
        max_parallel=1,
        max_cost=7,
    )
    fake = FakeRuns(cost=0)
    fake.cost = None  # e.g. an unpriced judge model
    _, state, _ = run_supervisor(monkeypatch, exp, fake, runs_base)
    # $3 reserved per run and never released: only two fit in $7.
    assert len(state.runs) == 2 and len(state.skipped) == 2


def test_summary_markdown(runs_base, scenario, monkeypatch):
    exp = experiment.Experiment(name="sum", scenarios=[str(scenario)], vary={"swarm.agents": [1, 2]})
    run_supervisor(monkeypatch, exp, FakeRuns(cost=1.25), runs_base)
    path = listing.write_summary("sum", runs_base)
    text = path.read_text()
    assert path == runs_base / "experiments" / "sum" / "summary.md"
    assert "swarm.agents=1" in text and "swarm.agents=2" in text
    assert "Cost so far: $2.50" in text and "| done | none |" in text


def test_prepare_refuses_a_running_experiment(runs_base, scenario, tmp_path):
    f = write_exp(tmp_path, f"name: busy\nscenarios: [{scenario}]\n")
    exp = experiment.load_experiment(f)
    experiment.prepare(exp, f)
    state = experiment.read_supervisor("busy")
    state.pid, state.pid_started = os.getpid(), procs.start_time(os.getpid())
    experiment.write_supervisor(state)
    with pytest.raises(RuntimeError, match="already running"):
        experiment.prepare(exp, f)
    loaded, dry = experiment.load_prepared(experiment.experiment_dir("busy"))
    assert loaded.name == "busy" and dry is False and runs.scenario_file(loaded.scenarios[0]).exists()


def test_crashed_run_keeps_its_reservation(runs_base, scenario, monkeypatch):
    """A run whose process died without a final status is charged at least its reservation."""
    exp = experiment.Experiment(
        name="crash",
        scenarios=[str(scenario)],
        vary={"swarm.agents": [1, 2, 3, 4]},
        max_parallel=1,
        max_cost=7,
    )

    class Crashing(FakeRuns):
        def tick(self, sup):
            self.committed_seen.append(sup.committed())
            if self.running:
                rd = self.running.pop(0)
                status = read_status(rd)
                # Still says "running" with a small cost, but its process is gone.
                StatusWriter(
                    rd, status.model_copy(update={"pid": 999_999_99, "swarm_cost": CostSummary(usd=0.1)})
                )

    _, state, messages = run_supervisor(monkeypatch, exp, Crashing(cost=0), runs_base)
    assert len(state.runs) == 2 and len(state.skipped) == 2  # $3 charged each, not $0.10
    assert any("died" in m for m in messages)


def test_stop_experiment_does_not_signal_itself(runs_base, scenario, tmp_path):
    from swarmbench.runner import control

    f = write_exp(tmp_path, f"name: fg\nscenarios: [{scenario}]\n")
    experiment.prepare(experiment.load_experiment(f), f)
    state = experiment.read_supervisor("fg")
    state.pid, state.pid_started, state.state = os.getpid(), procs.start_time(os.getpid()), "running"
    experiment.write_supervisor(state)
    assert control.stop_experiment("fg", say=lambda m: None) == {}  # no KeyboardInterrupt
    assert experiment.read_supervisor("fg").state == "stopped"
