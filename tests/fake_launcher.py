"""Runs the swarm CLI with a fake engine and judge, for tests of background processes.

Tests make background runs and supervisors start through this file instead of
``python -m swarmbench.cli``, so the child processes use the fakes too. Nothing here calls
a model or Docker.

Environment variables control the fake run:
  FAKE_RUN_SECONDS  how long the fake swarm runs (default 0.5)
  FAKE_IGNORE_STOP  "1": ignore the stop file and SIGINT (to test hard stops)
  FAKE_IGNORE_FILE  "1": ignore the stop file but not SIGINT
  FAKE_RUN_COST     dollars the fake swarm reports (default 1.0)
  FAKE_VERDICT      the fake judge's verdict (default "minor")
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def fake_run_scenario(scenario, run_dir, status, dry_run=False):
    from swarmbench.types import CostSummary

    seconds = float(os.environ.get("FAKE_RUN_SECONDS", "0.5"))
    stubborn = os.environ.get("FAKE_IGNORE_STOP") == "1"
    agents = sum(t.agents for t in scenario.resolved_teams())
    status.update(
        state="running",
        agents_total=agents,
        agents_active=agents,
        messages=3,
        monitor_flags={"high": 1},
        swarm_cost=CostSummary(usd=float(os.environ.get("FAKE_RUN_COST", "1.0"))),
        compose_project=f"fake-{run_dir.run_id}",
        force=True,
    )
    end = time.monotonic() + seconds
    stop_file = run_dir.root / "stop_requested"
    while time.monotonic() < end:
        if stop_file.exists() and not stubborn and os.environ.get("FAKE_IGNORE_FILE") != "1":
            break  # like the engine: wind down cleanly and return
        try:
            time.sleep(0.05)
        except KeyboardInterrupt:
            if not stubborn:
                raise
    return write_log(run_dir, scenario.epochs)


def write_log(run_dir, epochs=1):
    """A real (tiny) Inspect log from the mock model, like the engine leaves behind.

    FAKE_OUTCOME sets the engine's per-sample outcome (e.g. agent_errors, monitor_stop);
    FAKE_SAMPLE_ERROR=1 makes the sample fail with an error.
    """
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import generate, solver

    @solver
    def boom():
        async def solve(state, generate):
            raise RuntimeError("container exploded")

        return solve

    metadata = {}
    outcome = os.environ.get("FAKE_OUTCOME")
    if outcome:
        problems = {
            "agent_errors": ["agent-2 crashed: out of memory"],
            "monitor_stop": ["stopped early by the monitor"],
        }
        metadata["swarm_outcome"] = {
            "ok": outcome == "ok",
            "outcome": outcome,
            "problems": problems.get(outcome, []),
        }
    task = Task(
        dataset=[Sample(input="work", metadata=metadata)],
        solver=boom() if os.environ.get("FAKE_SAMPLE_ERROR") == "1" else generate(),
        epochs=epochs,
    )
    logs = eval(task, model="mockllm/model", log_dir=str(run_dir.logs), display="none", fail_on_error=False)
    return [Path(log.location) for log in logs]


def fake_judge_run(run_dir, model=None):
    from swarmbench.status import read_status
    from swarmbench.types import CostSummary, JudgeReport

    verdict = os.environ.get("FAKE_VERDICT", "minor")
    report = JudgeReport(
        run_id=run_dir.run_id,
        scenario="fake",
        verdict=verdict,
        headline=f"Fake headline ({verdict})",
        summary="The fake swarm did fake things.",
        coverage="2/2 agents scanned",
        eval_awareness="none noticed",
    )
    status = read_status(run_dir)
    data = report.model_dump(mode="json")
    # FAKE_PROFILES: {"<scenario name>": {extra report fields} or [one per repeat]}, for the
    # judge's newer fields (levels, turning points, leads) that screens rank by.
    profiles = json.loads(os.environ.get("FAKE_PROFILES", "{}"))
    profile = profiles.get(status.scenario, {})
    if isinstance(profile, list):
        repeat = int(status.settings.get("repeat", 1))
        profile = profile[(repeat - 1) % len(profile)]
    data.update(profile)
    data["scenario"] = status.scenario
    run_dir.report_json.write_text(json.dumps([data]))
    # Like the real judge, write the judge's own fields into status.json.
    status.verdict = verdict
    status.headline = report.headline
    status.judge_cost = CostSummary(usd=0.25)
    run_dir.status.write_text(status.model_dump_json())
    return [report]


def install() -> None:
    from swarmbench import engine, judge
    from swarmbench.runner import procs

    engine.run_scenario = fake_run_scenario
    judge.judge_run = fake_judge_run
    procs.python_command = lambda *args: [sys.executable, str(Path(__file__).resolve()), *args]


if __name__ == "__main__":
    install()
    from swarmbench.cli import app

    app(sys.argv[1:], prog_name="swarm")
