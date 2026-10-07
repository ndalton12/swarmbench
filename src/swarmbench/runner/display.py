"""Rich output shared by the commands."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

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


def epochs_text(n: int) -> str:
    return f"{n} epoch" if n == 1 else f"{n} epochs"


def print_estimate(estimate: costs.CostEstimate) -> None:
    """The worst-case cost before launch, explained in a line or two."""
    usd = costs.format_usd
    if estimate.capped:
        uncapped = estimate.uncapped_per_epoch
        also = f" The token budgets alone would allow {usd(uncapped)}." if uncapped is not None else ""
        console.print(f"Cost cap: {usd(estimate.swarm_per_epoch)} per epoch (max_cost).{also}")
    else:
        for line in estimate.lines:
            console.print(f"  {line}")
    swarm_label = "swarm cap" if estimate.capped else "swarm"
    console.print(
        f"Worst case: [bold]{usd(estimate.total)}[/] = ({usd(estimate.swarm_per_epoch)} {swarm_label} "
        f"+ {usd(estimate.judge_per_epoch)} judge cap) x {epochs_text(estimate.epochs)}"
    )


def confirm_question(estimate: costs.CostEstimate) -> str:
    """What to ask before launching, saying what actually limits the spending."""
    usd = costs.format_usd
    if estimate.total is None:
        missing = ", ".join(estimate.unpriced_models) or "a model"
        return f"The worst-case cost is unknown (no price for {missing}). Launch anyway?"
    judging = f"the judge stops itself at {usd(estimate.judge_per_epoch)}"
    per_epoch = " per epoch" if estimate.epochs > 1 else ""
    if estimate.capped:
        return (
            f"The dollar cap (max_cost) stops the swarm at {usd(estimate.swarm_per_epoch)}{per_epoch}, "
            f"and {judging}{per_epoch}: at most {usd(estimate.total)} in all. Launch?"
        )
    if estimate.max_cost is not None:
        return (
            f"The token budgets limit the swarm to {usd(estimate.swarm_per_epoch)}{per_epoch}, within its "
            f"{usd(estimate.max_cost)} max_cost, and {judging}{per_epoch}: at most {usd(estimate.total)}. "
            "Launch?"
        )
    return (
        f"No max_cost is set, so only the token budgets limit the swarm, to "
        f"{usd(estimate.swarm_per_epoch)}{per_epoch}; {judging}{per_epoch}: at most {usd(estimate.total)}. "
        "Launch?"
    )


def terminal_console(file) -> Console:
    return Console(file=file, highlight=False)


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
        if status.error:
            label = "Problem" if status.state == "failed" else "Note"
            console.print(f"[{'red' if label == 'Problem' else 'yellow'}]{label}: {status.error}[/]")
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


# When a table is too wide for the terminal, these columns give way, in this order: first
# each is cut short (with an ellipsis) down to MIN_SQUEEZED, then, if it still doesn't fit,
# dropped. Every other column (run name, state, verdict, cost, ...) is always shown whole.
SQUEEZE = ["Scenario", "Settings", "Eval awareness", "Problem", "Top behavior", "Group", "Headline"]
MIN_SQUEEZED = 12


class FitTable:
    """A table that fits the terminal: nothing wraps, and only the text columns in SQUEEZE
    are shortened or dropped to make room."""

    def __init__(self, *columns: str, squeeze: list[str] | None = None) -> None:
        self.columns = list(columns)
        self.squeeze = SQUEEZE if squeeze is None else squeeze
        self.rows: list[list[str]] = []

    def add_row(self, *cells: object) -> None:
        self.rows.append([str(c) for c in cells])

    def layout(self, max_width: int) -> tuple[list[int], dict[int, int]]:
        """Which columns to show, and the reduced width of any that were cut short."""
        cells = [[Text.from_markup(c).cell_len for c in row] for row in self.rows]
        widths = [max([len(name)] + [r[i] for r in cells]) for i, name in enumerate(self.columns)]
        shown = list(range(len(self.columns)))

        def excess() -> int:
            return sum(fixed.get(i, widths[i]) for i in shown) + 2 * (len(shown) - 1) - max_width

        fixed: dict[int, int] = {}
        giving = [self.columns.index(n) for n in self.squeeze if n in self.columns]
        for i in giving:
            if excess() <= 0:
                break
            fixed[i] = max(min(widths[i], MIN_SQUEEZED), widths[i] - excess())
        for i in giving:
            if excess() <= 0:
                break
            shown.remove(i)
        return shown, fixed

    def __rich_console__(self, console: Console, options):
        shown, fixed = self.layout(options.max_width)
        t = Table(box=None, pad_edge=False, header_style="bold")
        for i in shown:
            name = self.columns[i]
            if i in fixed:
                t.add_column(name, no_wrap=True, overflow="ellipsis", width=fixed[i])
            else:
                natural = max([len(name)] + [Text.from_markup(r[i]).cell_len for r in self.rows])
                t.add_column(name, no_wrap=True, min_width=natural)
        for row in self.rows:
            t.add_row(*(row[i] for i in shown))
        yield t


def table(*columns: str, squeeze: list[str] | None = None) -> FitTable:
    """A table that fits the terminal. ``squeeze`` lists the columns that may be shortened
    or dropped, most willing first (default: SQUEEZE)."""
    return FitTable(*columns, squeeze=squeeze)
