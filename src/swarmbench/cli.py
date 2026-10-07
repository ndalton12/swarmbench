"""The ``swarm`` command line. Owned by the runner teammate.

Every command is a thin wrapper: the work lives in swarmbench.engine,
swarmbench.runner, swarmbench.judge and swarmbench.design.
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Launch, monitor and judge agent swarms.")
design_app = typer.Typer(no_args_is_help=True, help="Draft and revise scenarios.")
app.add_typer(design_app, name="design")


@app.command()
def run(
    scenario: Path,
    agents: int | None = typer.Option(None, help="Agents per team."),
    model: str | None = typer.Option(None, help="Model for every agent, e.g. anthropic/claude-sonnet-5-5."),
    effort: str | None = typer.Option(None, help="low | medium | high | xhigh | max"),
    budget: str | None = typer.Option(None, help="Token budget per team, e.g. 2M."),
    max_cost: float | None = typer.Option(None, help="Dollar cap for the run."),
    harness: str | None = typer.Option(None, help="react | claude_code | codex_cli"),
    messaging: str | None = typer.Option(None, help="direct | board | both | off"),
    epochs: int | None = typer.Option(None),
    detach: bool = typer.Option(False, "--detach", "-d", help="Run in the background."),
    dry_run: bool = typer.Option(False, help="Use the mock model: no API calls."),
) -> None:
    """Run a scenario, judge it, and print the verdict."""
    raise NotImplementedError


def main() -> None:
    app()
