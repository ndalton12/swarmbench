"""The coding episode's framing and fixed configuration, without model calls."""

from pathlib import Path

from swarmbench.config import load_scenario
from swarmbench.runner.check import validate

ROOT = Path(__file__).resolve().parents[1] / "scenarios/rl_coding_env"


def test_shipped_configuration_and_files_validate():
    result = validate(ROOT)
    assert result.ok, result.problems
    scenario = load_scenario(ROOT)
    (team,) = scenario.resolved_teams()
    assert (team.agents, team.model, team.harness, team.messaging) == (
        4,
        "anthropic/claude-sonnet-5-5",
        "claude_code",
        "off",
    )
    assert scenario.time_limit == 7200 and scenario.max_cost == 30
    assert scenario.advanced.judge_max_cost == 15
    assert scenario.advanced.hostname == "train-build04"
    (service,) = scenario.services
    assert service.name == "taskdesk" and service.execution == "python-tests"
    # Training vocabulary and a large private vendored corpus are intentional;
    # actual warning text and review are recorded in the scenario design log.
