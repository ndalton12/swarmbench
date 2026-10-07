"""Experiments: a grid of runs over scenarios and varied settings, under a dollar budget.

An experiment file looks like::

    name: model-sweep
    scenarios: [scenarios/impossible_math]
    vary:
      swarm.model: [anthropic/claude-sonnet-5-5, anthropic/claude-opus-5-5]
      swarm.agents: [4, 12]
    epochs: 3
    max_parallel: 3
    max_cost: 150

A supervisor starts every combination as its own background run, at most ``max_parallel``
at a time. With ``max_cost``, each run reserves its worst case before it starts: its
``max_cost`` times its epochs, plus the judge's own cap per epoch
(``advanced.judge_max_cost``, or by default 25% of max_cost). A run starts only if its
reservation fits in what is left of the budget. When a run finishes cleanly with a known
cost, that cost replaces its reservation; a run that crashed, was stopped or has an unknown
cost is charged at least its reservation.

The budget is a careful estimate, not a hard guarantee. Inspect checks a run's cost_limit
after each model call, so agents with calls in flight can take a run slightly past its cap,
and the judge may finish one model call after reaching its cap. Any
overspend is counted once the run reports it, which reduces what later runs may reserve.
"""

from __future__ import annotations

import itertools
import json
import os
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from swarmbench import costs
from swarmbench.config import Scenario
from swarmbench.paths import RunDir
from swarmbench.runner import procs, runs
from swarmbench.status import StatusWriter, read_status
from swarmbench.types import CostSummary, RunStatus, now


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    scenarios: list[str]
    vary: dict[str, list[Any]] = Field(default_factory=dict)
    epochs: int | None = None
    """Epochs for every run (None: each scenario's own setting)."""
    max_parallel: int = Field(default=1, ge=1)
    max_cost: float | None = None
    """Dollar budget for the whole experiment, including epochs and judging."""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v or "/" in v or v.startswith("."):
            raise ValueError("experiment names must be plain folder names")
        return v

    @field_validator("vary")
    @classmethod
    def _vary(cls, v: dict[str, list[Any]]) -> dict[str, list[Any]]:
        for key, values in v.items():
            if not isinstance(values, list) or not values:
                raise ValueError(f"vary.{key} must be a non-empty list")
        return v


def load_experiment(path: str | Path) -> Experiment:
    """Read an experiment file. Scenario paths are taken relative to the current folder,
    or to the experiment file's folder if they don't exist there."""
    path = Path(path)
    exp = Experiment.model_validate(yaml.safe_load(path.read_text()) or {})
    resolved = []
    for s in exp.scenarios:
        p = Path(s)
        if not p.exists() and (path.parent / s).exists():
            p = path.parent / s
        resolved.append(str(p.resolve()))
    exp.scenarios = resolved
    return exp


@dataclass
class PlannedRun:
    scenario_path: str
    settings: dict[str, Any]
    """What this run changes, as dotted keys (shown in listings)."""
    overrides: dict[str, Any]
    scenario: Scenario
    reserve: float | None
    """Dollars this run reserves from the budget (None: the experiment has no budget)."""
    estimate: costs.CostEstimate

    def label(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in self.settings.items()) or self.scenario.name


def plan(exp: Experiment) -> list[PlannedRun]:
    """Every run of the experiment, checked up front. Raises ValueError listing all problems."""
    keys = list(exp.vary)
    combos = list(itertools.product(*(exp.vary[k] for k in keys))) if keys else [()]
    problems: list[str] = []
    planned: list[PlannedRun] = []
    for scenario_path in exp.scenarios:
        for combo in combos:
            settings: dict[str, Any] = dict(zip(keys, combo))
            if len(exp.scenarios) > 1:
                settings = {"scenario": Path(scenario_path).name, **settings}
            flags = {k: v for k, v in settings.items() if k != "scenario"}
            if exp.epochs is not None:
                flags["epochs"] = exp.epochs
            try:
                scenario, overrides = runs.resolve(scenario_path, flags)
            except Exception as e:  # noqa: BLE001 - reported together below
                problems.append(f"{scenario_path} with {flags}: {e}")
                continue
            reserve = None
            if exp.max_cost is not None:
                if scenario.max_cost is None:
                    problems.append(
                        f"{scenario.name}: the experiment has max_cost, so every run needs its own "
                        "max_cost (set it in the scenario or vary it)"
                    )
                    continue
                reserve = costs.reservation(scenario)
            planned.append(
                PlannedRun(
                    scenario_path, settings, overrides, scenario, reserve, costs.estimate_max_cost(scenario)
                )
            )
    if exp.max_cost is not None:
        models = sorted({t.model for p in planned for t in p.scenario.resolved_teams()})
        missing = costs.unpriced(models)
        if missing:
            problems.append(f"no price for {', '.join(missing)}: add it to prices.yaml to use max_cost")
        too_big = [p for p in planned if p.reserve is not None and p.reserve > exp.max_cost]
        for p in too_big:
            problems.append(
                f"{p.label()}: reserves ${p.reserve:,.2f}, more than the whole budget ${exp.max_cost:,.2f}"
            )
    if problems:
        raise ValueError("\n".join(problems))
    return planned


# ---- the experiment folder -------------------------------------------------------------


def experiments_base(base: Path | None = None) -> Path:
    return (base or runs.runs_base()) / "experiments"


def experiment_dir(name: str, base: Path | None = None) -> Path:
    return experiments_base(base) / name


class SupervisorState(BaseModel):
    """runs/experiments/<name>/supervisor.json, written by the supervisor process."""

    name: str
    pid: int | None = None
    pid_started: float | None = None
    state: str = "starting"
    """starting, running, done or stopped"""
    started: datetime = Field(default_factory=now)
    updated: datetime = Field(default_factory=now)
    budget: float | None = None
    committed: float = 0.0
    """Actual cost of finished runs plus reservations of running ones."""
    total_runs: int = 0
    runs: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    """Runs that never started, with the reason."""
    dry_run: bool = False


def supervisor_file(name: str, base: Path | None = None) -> Path:
    return experiment_dir(name, base) / "supervisor.json"


def read_supervisor(name: str, base: Path | None = None) -> SupervisorState | None:
    try:
        return SupervisorState.model_validate_json(supervisor_file(name, base).read_text())
    except (FileNotFoundError, ValueError):
        return None


def write_supervisor(state: SupervisorState, base: Path | None = None) -> None:
    state.updated = now()
    file = supervisor_file(state.name, base)
    tmp = file.with_suffix(".json.tmp")
    tmp.write_text(state.model_dump_json(indent=2))
    os.replace(tmp, file)


def supervisor_alive(name: str, base: Path | None = None) -> bool:
    state = read_supervisor(name, base)
    return bool(state and procs.is_alive(state.pid, state.pid_started))


def prepare(exp: Experiment, source: Path, dry_run: bool = False, base: Path | None = None) -> Path:
    """Create the experiment folder with a copy of the experiment file. Refuses if the same
    experiment is already running."""
    folder = experiment_dir(exp.name, base)
    if supervisor_alive(exp.name, base):
        raise RuntimeError(f"experiment {exp.name!r} is already running (swarm stop {exp.name} to stop it)")
    folder.mkdir(parents=True, exist_ok=True)
    # The experiment as it will run (scenario paths resolved, command-line changes applied).
    (folder / "experiment.yaml").write_text(yaml.safe_dump(exp.model_dump(), sort_keys=False))
    (folder / "launch.json").write_text(json.dumps({"source": str(source), "dry_run": dry_run}, indent=2))
    write_supervisor(SupervisorState(name=exp.name, dry_run=dry_run, budget=exp.max_cost), base)
    return folder


def start_detached(name: str, base: Path | None = None) -> int:
    folder = experiment_dir(name, base)
    pid, _ = procs.spawn_detached(procs.python_command("_supervise", str(folder)), folder / "supervisor.log")
    # The supervisor records its own pid in supervisor.json when it starts.
    return pid


def load_prepared(folder: Path) -> tuple[Experiment, bool]:
    """The experiment and dry-run flag saved by ``prepare``."""
    exp = Experiment.model_validate(yaml.safe_load((folder / "experiment.yaml").read_text()))
    launch = json.loads((folder / "launch.json").read_text())
    return exp, bool(launch.get("dry_run"))


# ---- the supervisor --------------------------------------------------------------------


def run_cost(status: RunStatus | None) -> float | None:
    """Swarm plus judge dollars for a run, or None if unknown."""
    if status is None:
        return None
    return costs.summary_usd(status.swarm_cost, status.judge_cost)


def _known(summary: CostSummary | None) -> float:
    if summary is None:
        return 0.0
    if summary.usd is not None:
        return summary.usd
    return sum(v for v in summary.by_model.values() if v is not None)


def logged_cost(run_dir: RunDir, status: RunStatus | None) -> float:
    """Known dollars from every sample in the run's Inspect logs, plus the judge's known spend.
    Settles a run's cost over all epochs even if its live status covered fewer."""
    logs = run_dir.eval_logs()
    swarm = costs.eval_logs_cost(logs) if logs else None
    return _known(swarm) + (_known(status.judge_cost) if status else 0.0)


def known_cost(status: RunStatus | None) -> float:
    """Dollars a run is known to have spent: the parts of its cost that are priced."""
    if status is None:
        return 0.0
    return _known(status.swarm_cost) + _known(status.judge_cost)


@dataclass
class _Active:
    planned: PlannedRun
    run_dir: RunDir
    pid: int
    started: float
    """Start time of the run's process, from when the supervisor launched it."""


@dataclass
class Supervisor:
    """Starts the planned runs, at most ``max_parallel`` at a time, within the budget."""

    exp: Experiment
    planned: list[PlannedRun]
    dry_run: bool = False
    base: Path | None = None
    poll: float = 2.0
    start_run: Callable[[RunDir], tuple[int, float]] = runs.start_detached
    say: Callable[[str], None] = print
    active: list[_Active] = field(default_factory=list)
    spent: float = 0.0
    stop_requested: bool = False

    def committed(self) -> float:
        return self.spent + sum(a.planned.reserve or 0.0 for a in self.active)

    def fits(self, p: PlannedRun) -> bool:
        if self.exp.max_cost is None or p.reserve is None:
            return True
        return self.committed() + p.reserve <= self.exp.max_cost + 1e-9

    def _launch(self, p: PlannedRun) -> _Active:
        launch = runs.Launch(
            scenario_path=p.scenario_path,
            overrides=p.overrides,
            dry_run=self.dry_run,
            experiment=self.exp.name,
            settings={
                k: v if isinstance(v, (str, int, float, bool)) else str(v) for k, v in p.settings.items()
            },
        )
        run_dir = runs.prepare(p.scenario, launch, self.base)
        pid, started = self.start_run(run_dir)
        self.say(f"started {run_dir.run_id} ({p.label()})")
        return _Active(p, run_dir, pid, started)

    def _finished(self, a: _Active) -> bool:
        """True once the run's process has ended. Then charges the run to the budget: its
        actual cost if it finished cleanly with a known cost, otherwise at least its
        reservation (a crashed or stopped run may have spent more than it last reported)."""
        status = read_status(a.run_dir)
        recorded = status is not None and status.pid is not None
        pid, started = (status.pid, status.pid_started) if recorded else (a.pid, a.started)
        running = status is None or status.state in runs.ACTIVE_STATES
        if running and procs.is_alive(pid, started):
            return False
        died = running
        if died:
            self._clean_up_dead(a, status)
        cost = run_cost(status)
        known = max(known_cost(status), logged_cost(a.run_dir, status))
        reserve = a.planned.reserve or 0.0
        if status is not None and status.state == "done" and cost is not None:
            self.spent += max(cost, known)
        else:
            # Unknown parts are covered by the reservation; known spending is never ignored.
            self.spent += max(known, reserve)
        state = "died" if died else status.state
        self.say(
            f"finished {a.run_dir.run_id}: {state}"
            + (f", {status.verdict}" if status and status.verdict else "")
        )
        return True

    def _clean_up_dead(self, a: _Active, status: RunStatus | None) -> None:
        """A run whose process died: take down its containers and record it as failed."""
        from swarmbench.runner import docker

        docker.remove_run(a.run_dir.root, a.run_dir.run_id, status.compose_project if status else None)
        if status is not None:
            update = {"state": "failed", "finished": now(), "error": "the run's process died"}
            StatusWriter(a.run_dir, status.model_copy(update=update))

    def _on_signal(self, signum: int, frame: Any) -> None:
        self.stop_requested = True

    def run(self, state: SupervisorState) -> SupervisorState:
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)
        state.pid, state.pid_started = os.getpid(), procs.start_time(os.getpid())
        state.state, state.total_runs, state.budget = "running", len(self.planned), self.exp.max_cost
        write_supervisor(state, self.base)
        pending = list(self.planned)
        try:
            while pending or self.active:
                procs.reap()
                self.active = [a for a in self.active if not self._finished(a)]
                if self.stop_requested:
                    break
                started_any = True
                while started_any and pending and len(self.active) < self.exp.max_parallel:
                    started_any = False
                    for p in list(pending):
                        if self.fits(p):
                            pending.remove(p)
                            a = self._launch(p)
                            self.active.append(a)
                            state.runs.append(a.run_dir.run_id)
                            started_any = True
                            break
                if pending and not self.active:
                    # Nothing is running, so the budget left won't grow: these can never start.
                    for p in pending:
                        left = (self.exp.max_cost or 0) - self.committed()
                        reason = f"{p.label()}: needs ${p.reserve:,.2f}, only ${left:,.2f} left in the budget"
                        state.skipped.append(reason)
                        self.say(f"skipped {reason}")
                    pending = []
                state.committed = self.committed()
                write_supervisor(state, self.base)
                if pending or self.active:
                    time.sleep(self.poll)
        finally:
            if self.stop_requested:
                for p in pending:
                    state.skipped.append(f"{p.label()}: experiment stopped")
                # Ask the runs to wind down; swarm stop escalates if they don't.
                for a in self.active:
                    runs.request_stop(a.run_dir, f"experiment {self.exp.name} stopped")
                state.state = "stopped"
            else:
                state.state = "done"
            state.committed = self.committed()
            write_supervisor(state, self.base)
            signal.signal(signal.SIGINT, signal.default_int_handler)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        return state


def supervise(folder: Path, base: Path | None = None, poll: float = 2.0) -> SupervisorState:
    """Body of the background supervisor process for a prepared experiment folder."""
    exp, dry_run = load_prepared(folder)
    planned = plan(exp)
    state = read_supervisor(exp.name, base) or SupervisorState(name=exp.name)
    sup = Supervisor(exp, planned, dry_run=dry_run, base=base, poll=poll, say=lambda m: print(m, flush=True))
    state = sup.run(state)
    from swarmbench.runner.listing import write_summary

    write_summary(exp.name, base)
    return state
