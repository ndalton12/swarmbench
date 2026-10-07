"""Swarm engine: Inspect task, orchestrator, harnesses, message bus and board, sandbox.

Owned by the engine teammate. See docs/interfaces.md sections 1, 2, 4 and 5.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task

from swarmbench.config import Scenario
from swarmbench.paths import RunDir
from swarmbench.status import StatusWriter


def swarm_task(scenario: Scenario, run_dir: RunDir, dry_run: bool = False) -> Task:
    raise NotImplementedError


def run_scenario(
    scenario: Scenario, run_dir: RunDir, status: StatusWriter, dry_run: bool = False
) -> list[Path]:
    raise NotImplementedError


def current_agent() -> str | None:
    """Name of the agent whose task is currently running (None outside an agent)."""
    raise NotImplementedError
