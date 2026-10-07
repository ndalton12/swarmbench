"""What ``swarm ps`` and ``swarm list`` show, and the experiment summary file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from swarmbench import costs
from swarmbench.paths import RunDir, list_runs
from swarmbench.runner import procs, runs
from swarmbench.runner.experiment import experiment_dir, experiments_base, read_supervisor, run_cost
from swarmbench.status import read_status
from swarmbench.types import RunStatus, now

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
STARTUP_SECONDS = 120


def effective_state(status: RunStatus) -> str:
    """The recorded state, or ``died`` if the run says it is active but its process is gone."""
    if status.state not in runs.ACTIVE_STATES:
        return status.state
    if status.state == "starting" and status.pid is None:
        # The worker records its pid within seconds of launch; much later means it never started.
        age = (now() - status.updated).total_seconds()
        return "starting" if age < STARTUP_SECONDS else "died"
    return status.state if procs.is_alive(status.pid, status.pid_started) else "died"


def elapsed(status: RunStatus, at: datetime | None = None) -> str:
    end = status.finished or at or now()
    seconds = max(0, int((end - status.started).total_seconds()))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def flags_text(status: RunStatus) -> str:
    parts = [f"{status.monitor_flags[s]} {s}" for s in SEVERITY_ORDER if status.monitor_flags.get(s)]
    return ", ".join(parts) or "-"


def cost_text(status: RunStatus) -> str:
    return costs.format_usd(run_cost(status))


@dataclass
class RunRow:
    run_dir: RunDir
    status: RunStatus
    state: str

    @property
    def run_id(self) -> str:
        return self.run_dir.run_id


def all_rows(base: Path | None = None, experiment: str | None = None) -> list[RunRow]:
    """Every run with a readable status, newest first."""
    rows = []
    for run_dir in list_runs(base or runs.runs_base()):
        status = read_status(run_dir)
        if status is None:
            continue
        if experiment is not None and status.experiment != experiment:
            continue
        rows.append(RunRow(run_dir, status, effective_state(status)))
    return rows


def live_rows(base: Path | None = None) -> list[RunRow]:
    """Runs that are active, or that say they are active but whose process died."""
    return [r for r in all_rows(base) if r.status.state in runs.ACTIVE_STATES]


def live_experiments(base: Path | None = None) -> list[str]:
    folder = experiments_base(base)
    if not folder.exists():
        return []
    out = []
    for d in sorted(folder.iterdir()):
        state = read_supervisor(d.name, base)
        if state and procs.is_alive(state.pid, state.pid_started):
            out.append(d.name)
    return out


def eval_awareness(run_dir: RunDir) -> str:
    texts = []
    for r in runs.read_reports(run_dir):
        if r.eval_awareness and r.eval_awareness not in texts:
            texts.append(r.eval_awareness)
    return " / ".join(texts)


def settings_text(status: RunStatus) -> str:
    return ", ".join(f"{k}={v}" for k, v in status.settings.items())


def _cell(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def summary_markdown(name: str, rows: list[RunRow], base: Path | None = None) -> str:
    sup = read_supervisor(name, base)
    total = 0.0
    unknown = 0
    for r in rows:
        c = run_cost(r.status)
        if c is None:
            unknown += 1
        else:
            total += c
    lines = [f"# Experiment {name}", ""]
    lines.append(
        f"{len(rows)} runs. Cost so far: {costs.format_usd(total)}"
        + (f" ({unknown} runs with unknown cost)" if unknown else "")
        + "."
    )
    if sup and sup.budget is not None:
        lines.append(f"Budget: {costs.format_usd(sup.budget)}.")
    if sup:
        lines.append(f"Supervisor: {sup.state}.")
    lines += [
        "",
        "| Run | Settings | State | Verdict | Headline | Eval awareness | Cost |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: r.run_id):
        lines.append(
            f"| {r.run_id} | {_cell(settings_text(r.status))} | {r.state} | {r.status.verdict or '-'} | "
            f"{_cell(r.status.headline) or '-'} | {_cell(eval_awareness(r.run_dir)) or '-'} | {cost_text(r.status)} |"
        )
    if sup and sup.skipped:
        lines += ["", "Runs that did not start:", ""] + [f"- {s}" for s in sup.skipped]
    return "\n".join(lines) + "\n"


def write_summary(name: str, base: Path | None = None) -> Path:
    rows = all_rows(base, experiment=name)
    folder = experiment_dir(name, base)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "summary.md"
    path.write_text(summary_markdown(name, rows, base))
    return path
