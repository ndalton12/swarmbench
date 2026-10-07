"""Rich output shared by the commands."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from swarmbench import costs
from swarmbench.paths import RunDir
from swarmbench.runner.experiment import run_cost
from swarmbench.types import JudgeReport, RunStatus

console = Console(highlight=False)
err = Console(stderr=True, highlight=False)

VERDICT_STYLE = {
    "none": "bold green",
    "minor": "bold yellow",
    "concerning": "bold dark_orange",
    "severe": "bold red",
}
STATE_STYLE = {
    "done": "green",
    "failed": "red",
    "died": "red",
    "stopped": "yellow",
    "running": "cyan",
    "judging": "cyan",
}


def verdict_text(verdict: str | None) -> str:
    if not verdict:
        return "-"
    return f"[{VERDICT_STYLE.get(verdict, 'bold')}]{verdict}[/]"


def state_text(state: str) -> str:
    style = STATE_STYLE.get(state)
    return f"[{style}]{state}[/]" if style else state


def view_commands(run_dir: RunDir) -> list[str]:
    return [f"swarm view {run_dir.root}", f"swarm view {run_dir.root} --scout"]


def print_estimate(estimate: costs.CostEstimate) -> None:
    for line in estimate.lines:
        console.print(f"  {line}")
    swarm = costs.format_usd(estimate.swarm_per_epoch)
    judge = costs.format_usd(estimate.judge_per_epoch)
    cap = " (capped by max_cost)" if estimate.capped else ""
    console.print(
        f"Worst-case cost: [bold]{costs.format_usd(estimate.total)}[/] = "
        f"(swarm {swarm}{cap} + judge allowance {judge}) x {estimate.epochs} epoch(s)"
    )


def print_result(run_dir: RunDir, status: RunStatus, reports: list[JudgeReport]) -> None:
    """The end of a run: verdict, headline, summary, cost and where to look next."""
    console.print()
    if reports or status.state == "done":
        console.print(f"Verdict: {verdict_text(status.verdict)}")
        if status.headline:
            console.print(f"[bold]{status.headline}[/]")
        if len(reports) == 1:
            if reports[0].summary:
                console.print(reports[0].summary)
            if reports[0].coverage:
                console.print(f"[dim]Coverage: {reports[0].coverage}[/]")
        for r in reports if len(reports) > 1 else []:
            console.print(f"  epoch {r.epoch}: {verdict_text(r.verdict)} {r.headline}")
    else:
        console.print(f"Run {state_text(status.state)}" + (f": {status.error}" if status.error else ""))
    swarm = costs.format_usd(costs.summary_usd(status.swarm_cost))
    judge = costs.format_usd(costs.summary_usd(status.judge_cost))
    unpriced = sorted(set(status.swarm_cost.unpriced_models) | set(status.judge_cost.unpriced_models))
    note = f" (no price for {', '.join(unpriced)})" if unpriced else ""
    console.print(f"Cost: swarm {swarm}, judge {judge}, total {costs.format_usd(run_cost(status))}{note}")
    console.print(f"Run folder: {run_dir.root}")
    for cmd in view_commands(run_dir):
        console.print(f"  [dim]$[/] {cmd}")


def table(*columns: str) -> Table:
    t = Table(box=None, pad_edge=False, header_style="bold")
    for c in columns:
        t.add_column(c, overflow="fold")
    return t
