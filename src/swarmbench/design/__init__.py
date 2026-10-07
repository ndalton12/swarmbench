"""Scenario designer: draft new scenarios and revise existing ones from run results.

Public interface (used by the CLI):

    new_scenario(idea, out_dir=None, model=None) -> Path
        Drafts a full scenario folder (scenario.yaml, prompt.md, notes.md, a lived-in
        workspace, optional protected/ and history.yaml) with a strong model, repairs it
        until it loads, then runs a realism review that revises it. Writes
        scenarios/<slug>/ (or out_dir) plus design_log.md.

    iterate_scenario(scenario_dir, run_dirs, out_dir=None, model=None) -> Path
        Reads the runs' judge reports, monitor flags and scanner summaries, and writes
        <scenario>_vN/ (the next free N) with CHANGES.md explaining each change and the
        evidence behind it.

    scenario_from_moment(run_dir, moment, out_dir=None, model=None, scenario_dir=None) -> Path
        Drafts a new scenario that recreates a striking moment (a quote or short
        description) from a past run.

All three print a short plain-language summary (pass ``echo=None`` to silence it),
never overwrite anything, never write outside the output folder, and never launch
runs. ``model`` may be a model name or an Inspect ``Model`` (tests pass mockllm).
The ``*_async`` versions are for callers already inside an event loop.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import anyio
from inspect_ai.model import Model

from swarmbench.design.drafting import DesignError
from swarmbench.design.history import check_history, seed_workspace
from swarmbench.design.iterate import iterate_scenario_async
from swarmbench.design.llm import DEFAULT_DESIGN_MODEL
from swarmbench.design.new import Echo, new_scenario_async, scenario_from_moment_async
from swarmbench.paths import RunDir

__all__ = [
    "DEFAULT_DESIGN_MODEL",
    "DesignError",
    "check_history",
    "iterate_scenario",
    "iterate_scenario_async",
    "new_scenario",
    "new_scenario_async",
    "scenario_from_moment",
    "scenario_from_moment_async",
    "seed_workspace",
]


def new_scenario(
    idea: str,
    out_dir: Path | None = None,
    model: str | Model | None = None,
    *,
    scenarios_dir: Path | None = None,
    checklist: Path | None = None,
    critique: bool = True,
    echo: Echo | None = print,
) -> Path:
    return anyio.run(
        partial(
            new_scenario_async,
            idea,
            _path(out_dir),
            model,
            scenarios_dir=_path(scenarios_dir),
            checklist=_path(checklist),
            critique=critique,
            echo=echo,
        )
    )


def iterate_scenario(
    scenario_dir: Path,
    run_dirs: list[RunDir],
    out_dir: Path | None = None,
    model: str | Model | None = None,
    *,
    checklist: Path | None = None,
    echo: Echo | None = print,
) -> Path:
    runs = [r if isinstance(r, RunDir) else RunDir(Path(r)) for r in run_dirs]
    return anyio.run(
        partial(
            iterate_scenario_async,
            Path(scenario_dir),
            runs,
            _path(out_dir),
            model,
            checklist=_path(checklist),
            echo=echo,
        )
    )


def scenario_from_moment(
    run_dir: RunDir,
    moment: str,
    out_dir: Path | None = None,
    model: str | Model | None = None,
    *,
    scenario_dir: Path | None = None,
    scenarios_dir: Path | None = None,
    checklist: Path | None = None,
    echo: Echo | None = print,
) -> Path:
    run = run_dir if isinstance(run_dir, RunDir) else RunDir(Path(run_dir))
    return anyio.run(
        partial(
            scenario_from_moment_async,
            run,
            moment,
            _path(out_dir),
            model,
            scenario_dir=_path(scenario_dir),
            scenarios_dir=_path(scenarios_dir),
            checklist=_path(checklist),
            echo=echo,
        )
    )


def _path(value: Path | str | None) -> Path | None:
    return None if value is None else Path(value)
