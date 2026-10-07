"""Scenario designer: draft new scenarios and revise existing ones from results.

Owned by the designer teammate. Public interface used by the CLI:

    new_scenario(idea, out_dir, model=None) -> Path
    iterate_scenario(scenario_dir, run_dirs, out_dir=None, model=None) -> Path
"""

from __future__ import annotations

from pathlib import Path

from swarmbench.paths import RunDir


def new_scenario(idea: str, out_dir: Path | None = None, model: str | None = None) -> Path:
    raise NotImplementedError


def iterate_scenario(
    scenario_dir: Path,
    run_dirs: list[RunDir],
    out_dir: Path | None = None,
    model: str | None = None,
) -> Path:
    raise NotImplementedError
