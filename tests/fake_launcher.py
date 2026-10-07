"""Runs the swarm CLI with a fake engine and judge, for tests of background processes.

Tests make background runs and supervisors start through this file instead of
``python -m swarmbench.cli``, so the child processes use the fakes too. Nothing here calls
a model or Docker.

Environment variables control the fake run:
  FAKE_RUN_SECONDS  how long the fake swarm runs (default 0.5)
  FAKE_IGNORE_STOP  "1": keep running after a stop signal (to test hard stops)
  FAKE_RUN_COST     dollars the fake swarm reports (default 1.0)
  FAKE_VERDICT      the fake judge's verdict (default "minor")
"""

from __future__ import annotations

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
    while time.monotonic() < end:
        try:
            time.sleep(0.05)
        except KeyboardInterrupt:
            if not stubborn:
                raise
    log = run_dir.logs / "fake.eval"
    log.write_text("")
    return [log]


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
    run_dir.report_json.write_text("[" + report.model_dump_json() + "]")
    # Like the real judge, write the judge's own fields into status.json.
    status = read_status(run_dir)
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
