"""The run log: ``runs/RUNS.md``, one row per run, newest first, to tell runs apart at a glance.

Each row has the run's folder, the scenario, the models (the agents' and the judge's), how many
agents, how long it took, what it cost, the verdict and the judge's one-line answer. A copy for
scripts is written next to it as ``runs/runs.jsonl``.

Both files are rebuilt from every run's status.json whenever a run finishes, is judged again or
is listed, so a re-judged run's row is replaced, never duplicated. Writes are atomic, so runs that
finish together can't leave a half-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from swarmbench import costs
from swarmbench.paths import RunDir
from swarmbench.runner import listing, runs
from swarmbench.runner.experiment import run_cost

RUN_LOG = "RUNS.md"
RUN_LOG_JSONL = "runs.jsonl"


def _short_model(name: str | None) -> str:
    return (name or "?").split("/", 1)[-1]


def _models(run_dir: RunDir) -> tuple[str, int]:
    """The agents' models (with harness) and the number of agents, from the run's own scenario.yaml."""
    try:
        data = yaml.safe_load(run_dir.scenario.read_text()) or {}
    except Exception:
        return "?", 0
    swarm = data.get("swarm") or {}
    teams = data.get("teams") or [{}]
    used: list[str] = []
    agents = 0
    for team in teams:
        model = _short_model(team.get("model") or swarm.get("model"))
        harness = team.get("harness") or swarm.get("harness") or "react"
        n = int(team.get("agents") or swarm.get("agents") or 0)
        agents += n
        label = f"{model} ({harness})"
        if label not in used:
            used.append(label)
    return ", ".join(used), agents


def agent_models(run_dir: RunDir) -> str:
    """The agents' models, short (for ``swarm list``)."""
    models, _ = _models(run_dir)
    return ", ".join(m.split(" (", 1)[0] for m in models.split(", ")) if models != "?" else "?"


def _judge_model(run_dir: RunDir) -> str:
    """The model that judged the run, as its judging recorded it."""
    trace = run_dir.root / "judge_trace.json"
    try:
        data = json.loads(trace.read_text())
        first = data[0] if isinstance(data, list) else data
        model = (first.get("decisions") or {}).get("main_model")
        if model:
            return _short_model(model)
    except Exception:
        pass
    try:
        data = yaml.safe_load(run_dir.scenario.read_text()) or {}
        model = (data.get("advanced") or {}).get("judge_model")
    except Exception:
        model = None
    if model:
        return _short_model(model)
    from swarmbench import judge

    return _short_model(getattr(judge, "DEFAULT_JUDGE_MODEL", None))


def entry(row: listing.RunRow) -> dict[str, Any]:
    """One run's line in the log."""
    status = row.status
    agent_models, agents = _models(row.run_dir)
    judged = status.verdict is not None
    answer = status.headline or (status.error if row.state in ("failed", "stopped") else "") or ""
    return {
        "run": row.run_id,
        "folder": str(row.run_dir.root),
        "started": status.started.astimezone().isoformat() if status.started else None,
        "scenario": status.scenario,
        "group": status.experiment,
        "state": row.state,
        "models": agent_models,
        "judge": _judge_model(row.run_dir) if judged else None,
        "agents": agents,
        "took": listing.elapsed(status),
        "cost_swarm": costs.summary_usd(status.swarm_cost),
        "cost_judge": costs.summary_usd(status.judge_cost),
        "cost_total": run_cost(status),
        "verdict": status.verdict,
        "answer": answer,
    }


def _cell(text: Any) -> str:
    return str(text if text not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def markdown(entries: list[dict[str, Any]]) -> str:
    lines = [
        "# Run log",
        "",
        "One row per run, newest first. Rebuilt automatically when a run finishes or is judged again.",
        "",
        "| When (local time) | Run folder | Scenario | Agents' models | Agents | Took | Cost (swarm + judge) | Verdict | What happened |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        when = (e["started"] or "")[:16].replace("T", " ")
        cost = costs.format_usd(e["cost_total"])
        if e["cost_judge"]:
            cost += f" ({costs.format_usd(e['cost_swarm'])} + {costs.format_usd(e['cost_judge'])})"
        verdict = e["verdict"] or e["state"]
        if e["verdict"] and e["state"] in ("failed", "stopped"):
            verdict = f"{e['verdict']} ({e['state']})"
        judge = f"; judged by {e['judge']}" if e["judge"] else ""
        group = f" ({e['group']})" if e["group"] else ""
        lines.append(
            f"| {_cell(when)} | [{e['run']}]({e['run']}/) | {_cell(e['scenario'])}{_cell(group) if group else ''} | "
            f"{_cell(e['models'])}{_cell(judge) if judge else ''} | {e['agents'] or '-'} | {_cell(e['took'])} | "
            f"{_cell(cost)} | {_cell(verdict)} | {_cell(e['answer'])} |"
        )
    return "\n".join(lines) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_run_log(base: Path | None = None) -> Path:
    """Rebuild runs/RUNS.md and runs/runs.jsonl from every run's status. Returns the .md path."""
    folder = base or runs.runs_base()
    folder.mkdir(parents=True, exist_ok=True)
    entries = [entry(r) for r in listing.all_rows(folder)]
    _write_atomic(folder / RUN_LOG_JSONL, "".join(json.dumps(e) + "\n" for e in entries))
    md = folder / RUN_LOG
    _write_atomic(md, markdown(entries))
    return md


def refresh(base: Path | None = None) -> None:
    """Rebuild the run log, never failing the caller (it's a convenience, not part of a run)."""
    try:
        write_run_log(base)
    except Exception:
        pass
