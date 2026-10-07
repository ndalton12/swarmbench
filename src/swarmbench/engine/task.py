"""The Inspect task for a swarm run, and ``run_scenario`` for the runner."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import Model

from swarmbench.config import Scenario, dump_scenario
from swarmbench.paths import RunDir
from swarmbench.status import StatusWriter

from .compose import write_compose
from .image import build_base_image, build_team_image
from .layout import agent_infos, team_sandbox
from .mock import MockSwarmModel, mock_model
from .orchestrator import HOOKS, RunHooks, swarm_solver
from .provenance import write_provenance

TASK_NAME = "swarm"
COMPOSE_FILE = "compose.yaml"


def _approval(scenario: Scenario, run_dir: RunDir) -> list[Any] | None:
    try:
        from swarmbench.monitor import approval_policies  # type: ignore[attr-defined]
    except ImportError:
        return None
    return approval_policies(scenario, run_dir)


def build_images(scenario: Scenario, run_id: str | None = None, now: datetime | None = None) -> list[str]:
    base = build_base_image()
    now = now or datetime.now().astimezone()
    return [
        build_team_image(scenario, i, base, now=now, seed=run_id)
        for i in range(len(scenario.resolved_teams()))
    ]


def swarm_task(
    scenario: Scenario,
    run_dir: RunDir,
    dry_run: bool = False,
    *,
    images: list[str] | None = None,
    model: Model | None = None,
    run_start: datetime | None = None,
) -> Task:
    """One task, one sample per epoch. Builds the images and writes the compose file."""
    run_start = run_start or datetime.now().astimezone()
    images = images or build_images(scenario, run_dir.run_id, run_start)
    compose = write_compose(
        scenario, images, run_dir.run_id, run_dir.root / COMPOSE_FILE, str(run_dir.root.resolve())
    )
    teams = scenario.resolved_teams()
    metadata = {
        "swarm": {
            "scenario": scenario.name,
            "run_id": run_dir.run_id,
            "teams": [{"name": t.name, "sandbox": team_sandbox(t), "agents": t.agent_names()} for t in teams],
            "agents": [a.model_dump(mode="json") for a in agent_infos(scenario)],
        }
    }
    if dry_run and model is None:
        hooks = HOOKS.setdefault(run_dir.run_id, RunHooks())
        hooks.mock = hooks.mock or MockSwarmModel()
        model = mock_model(hooks.mock)
    task_model: Model | str | None = model if model is not None else teams[0].model
    return Task(
        name=TASK_NAME,
        dataset=[Sample(id=scenario.name, input=scenario.description or scenario.name, metadata=metadata)],
        solver=swarm_solver(
            scenario, str(run_dir.root), run_dir.run_id, dry_run=dry_run, run_start=run_start.isoformat()
        ),
        sandbox=("docker", str(compose)),
        approval=_approval(scenario, run_dir),
        epochs=scenario.epochs,
        time_limit=scenario.time_limit,
        model=task_model,
        metadata={"swarmbench": True},
    )


def _cost_config() -> Any:
    try:
        from swarmbench.costs import model_cost_config  # type: ignore[import-not-found]
    except ImportError:
        return None
    return model_cost_config()


def run_scenario(
    scenario: Scenario, run_dir: RunDir, status: StatusWriter, dry_run: bool = False, **eval_args: Any
) -> list[Path]:
    """Run a scenario end to end (without the judge) and return the .eval log paths."""
    run_dir.scenario.write_text(dump_scenario(scenario))
    status.update(force=True, agents_total=len(agent_infos(scenario)))
    run_start = datetime.now().astimezone()
    images = build_images(scenario, run_dir.run_id, run_start)
    write_provenance(scenario, run_dir, images)

    hooks = HOOKS.setdefault(run_dir.run_id, RunHooks())
    hooks.status = status
    task = swarm_task(scenario, run_dir, dry_run=dry_run, images=images, run_start=run_start)

    kwargs: dict[str, Any] = {
        "log_dir": str(run_dir.logs),
        "display": "none",
        "max_samples": 1,
        "fail_on_error": False,
    }
    cost_config = _cost_config()
    if cost_config is not None:
        kwargs["model_cost_config"] = cost_config
    if scenario.max_cost is not None:
        kwargs["cost_limit"] = scenario.max_cost
    kwargs.update(eval_args)
    try:
        logs = eval(task, **kwargs)
    finally:
        HOOKS.pop(run_dir.run_id, None)

    status.flush()
    return [Path(log.location) for log in logs if log.location]
