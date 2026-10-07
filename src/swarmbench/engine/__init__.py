"""Swarm engine: Inspect task, orchestrator, harnesses, message bus, sandbox.

Owned by the engine teammate. Public interface used by the CLI:

    run_scenario(scenario, run_dir, dry_run=False) -> list[Path]   # .eval logs
    swarm_task(scenario, run_dir) -> inspect_ai.Task
"""

from __future__ import annotations

from pathlib import Path

from swarmbench.config import Scenario
from swarmbench.paths import RunDir


def run_scenario(scenario: Scenario, run_dir: RunDir, dry_run: bool = False) -> list[Path]:
    raise NotImplementedError
