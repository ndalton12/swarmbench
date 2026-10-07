"""Dry runs: every model role is the mock model, and anything else is refused.

``dry_run_scenario`` rewrites the scenario before anything is built, so agents,
the monitor and the judge all resolve to ``mockllm/model``. As a hard guard, an
Inspect hook refuses any other model's generate call while a dry-run sample is
running (it fires before the provider is contacted).
"""

from __future__ import annotations

from contextvars import ContextVar

from inspect_ai.hooks import BeforeModelGenerate, Hooks, hooks
from inspect_ai.util import LimitExceededError

from swarmbench.config import Scenario

MOCK_MODEL = "mockllm/model"

_dry_run: ContextVar[bool] = ContextVar("swarmbench_dry_run", default=False)


def dry_run_scenario(scenario: Scenario) -> Scenario:
    """A copy of ``scenario`` whose every model role (agents, monitor, judge) is the mock model."""
    data = scenario.model_dump(mode="json")
    data["swarm"]["model"] = MOCK_MODEL
    for team in data.get("teams") or []:
        if team.get("model"):
            team["model"] = MOCK_MODEL
    advanced = data.setdefault("advanced", {})
    for role in ("monitor_model", "judge_model"):
        if advanced.get(role):
            advanced[role] = MOCK_MODEL
    out = Scenario.model_validate(data)
    out.root = scenario.root
    return out


def set_dry_run(value: bool) -> None:
    _dry_run.set(value)


def is_mock(model_name: str) -> bool:
    return model_name.startswith("mockllm/")


class RealModelInDryRun(LimitExceededError):
    def __init__(self, model_name: str) -> None:
        super().__init__(
            "custom", value=1, limit=0, message=f"dry run tried to call a real model: {model_name}"
        )


@hooks(name="swarmbench_dry_run_guard", description="Refuses real model calls during swarmbench dry runs.")
class DryRunGuard(Hooks):
    def enabled(self) -> bool:
        return True

    async def on_before_model_generate(self, data: BeforeModelGenerate) -> None:
        if _dry_run.get() and not is_mock(data.model_name):
            # Inspect re-raises limit errors from hooks (others are only logged), which ends the
            # sample; record it too, in case the caller swallows the error.
            from .orchestrator import add_problem

            add_problem(f"dry run tried to call a real model: {data.model_name} (refused)")
            raise RealModelInDryRun(data.model_name)
