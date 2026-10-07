"""``swarm check``: validate a scenario folder before it is run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from swarmbench import costs
from swarmbench.config import Scenario, load_scenario


@dataclass
class CheckResult:
    scenario: Scenario | None = None
    problems: list[str] = field(default_factory=list)
    """Things that must be fixed before the scenario can run."""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def validate(path: str | Path) -> CheckResult:
    """Load the scenario and check that every file it refers to exists."""
    try:
        scenario = load_scenario(path)
    except Exception as e:
        return CheckResult(problems=[f"scenario.yaml: {e}"])
    return validate_scenario(scenario)


def validate_scenario(scenario: Scenario) -> CheckResult:
    """Check a loaded scenario: its files exist and its models have prices."""
    result = CheckResult(scenario=scenario)

    for team in scenario.resolved_teams():
        who = f"team {team.name}: " if scenario.teams else ""
        if not scenario.path(team.prompt).is_file():
            result.problems.append(f"{who}prompt file {team.prompt} is missing")
        if team.workspace is not None and not scenario.path(team.workspace).is_dir():
            result.problems.append(f"{who}workspace folder {team.workspace}/ is missing")
    if scenario.protected and not scenario.path(scenario.protected).is_dir():
        result.problems.append(f"protected folder {scenario.protected}/ is missing")
    if not scenario.path(scenario.notes).is_file():
        result.warnings.append(f"{scenario.notes} is missing: the judge and designer get no notes")
    enc = scenario.encounter
    if enc and enc.via == "file":
        if not enc.source:
            result.problems.append("encounter via file needs a source file")
        elif not scenario.path(enc.source).is_file():
            result.problems.append(f"encounter source {enc.source} is missing")

    for problem in price_problems(scenario):
        (result.problems if scenario.max_cost is not None else result.warnings).append(problem)
    judge = scenario.advanced.judge_model
    if judge and costs.price_of(judge) is None:
        result.warnings.append(f"no price for the judge model {judge}: judge cost will show as unknown")
    return result


def price_problems(scenario: Scenario) -> list[str]:
    """Models used inside the run (agents and monitor) that have no price.

    Inspect refuses to enforce ``max_cost`` without a price for every model, so with a cap
    these stop the run from starting; without one their cost shows as unknown.
    """
    models = [t.model for t in scenario.resolved_teams()]
    if scenario.advanced.monitor_model:
        models.append(scenario.advanced.monitor_model)
    missing = costs.unpriced(models)
    if not missing:
        return []
    if scenario.max_cost is not None:
        return [f"max_cost is set but there is no price for {', '.join(missing)} (add it to prices.yaml)"]
    return [f"no price for {', '.join(missing)}: cost will show as unknown"]
