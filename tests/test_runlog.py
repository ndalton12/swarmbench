"""runs/RUNS.md: one row per run with its folder, scenario, models, time, cost and the judge's answer."""

from __future__ import annotations

import json
from datetime import timedelta

from swarmbench.paths import RunDir
from swarmbench.runner import runlog
from swarmbench.status import StatusWriter
from swarmbench.types import CostSummary, RunStatus, now


def _run(base, name, scenario_yaml, **status):
    rd = RunDir.create(name, base=base)
    rd.scenario.write_text(scenario_yaml)
    started = now() - timedelta(minutes=18)
    if status.get("finished"):
        status["finished"] = started + timedelta(minutes=18, seconds=5)
    StatusWriter(rd, RunStatus(run_id=rd.run_id, scenario=name, started=started, **status))
    return rd


def test_the_log_has_one_row_per_run_with_what_tells_runs_apart(tmp_path):
    rd = _run(
        tmp_path,
        "rival-swarms",
        "swarm: {agents: 3, model: openai/gpt-6.1-sol, harness: claude_code}\n"
        "teams: [{name: c07, agents: 3}, {name: c09, agents: 3}]\n",
        state="done",
        finished=now(),
        verdict="minor",
        headline="One agent thought about avoiding retirement.",
        swarm_cost=CostSummary(usd=3.0),
        judge_cost=CostSummary(usd=2.5),
        experiment="screen:gpt",
    )
    _run(
        tmp_path,
        "impossible-math",
        "swarm: {agents: 3, model: anthropic/claude-sonnet-5-5}\n",
        state="failed",
        finished=now(),
        error="agent-2 crashed: boom",
    )
    md = runlog.write_run_log(tmp_path).read_text()
    rows = [line for line in md.splitlines() if line.startswith("| 20")]
    assert len(rows) == 2
    row = next(r for r in rows if rd.run_id in r)
    for part in (
        f"[{rd.run_id}]({rd.run_id}/)",
        "rival-swarms (screen:gpt)",
        "gpt-6.1-sol (claude_code)",
        "| 6 |",
        "18m05s",
        "$5.50 ($3.00 + $2.50)",
        "| minor |",
        "One agent thought about avoiding retirement.",
    ):
        assert part in row, part
    assert "agent-2 crashed: boom" in md  # a run without a verdict says why
    entries = [json.loads(x) for x in (tmp_path / runlog.RUN_LOG_JSONL).read_text().splitlines()]
    assert {e["run"] for e in entries} == {r.split("](")[0].split("[")[-1] for r in rows}


def test_rebuilding_replaces_a_rejudged_runs_row(tmp_path):
    rd = _run(
        tmp_path,
        "rival-swarms",
        "swarm: {model: openai/gpt-6.1-sol}\n",
        state="done",
        finished=now(),
        verdict="none",
        headline="Not fully assessed: the budget ran out.",
    )
    runlog.write_run_log(tmp_path)
    status = RunStatus.model_validate_json(rd.status.read_text())
    StatusWriter(rd, status.model_copy(update={"headline": "Nothing concerning happened."}))
    md = runlog.write_run_log(tmp_path).read_text()
    assert (
        md.count(rd.run_id + "]") == 1 and "Nothing concerning happened." in md and "budget ran out" not in md
    )


def test_a_broken_run_folder_never_stops_the_log(tmp_path):
    rd = _run(tmp_path, "x", "not: [valid", state="done", finished=now())
    runlog.refresh(tmp_path)
    assert rd.run_id in (tmp_path / runlog.RUN_LOG).read_text()
