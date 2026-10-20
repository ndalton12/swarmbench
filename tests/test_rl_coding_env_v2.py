"""Configuration contract for the revised coding episode; no model calls."""

import json
from pathlib import Path

from swarmbench.config import load_scenario
from swarmbench.runner.check import validate

ROOT = Path(__file__).resolve().parents[1] / "scenarios/rl_coding_env_v2"


def test_revised_episode_has_twenty_fixed_tasks_and_no_builtin_messaging():
    result = validate(ROOT)
    assert result.ok, result.problems
    scenario = load_scenario(ROOT)
    (team,) = scenario.resolved_teams()
    assert scenario.name == "rl-coding-env-v2"
    assert (team.agents, team.harness, team.messaging) == (4, "claude_code", "off")
    assert scenario.time_limit == 7200 and scenario.max_cost == 30
    assert scenario.advanced.judge_max_cost == 15
    assert scenario.services[0].execution == "python-tests"
    catalog = json.loads((ROOT / "services/taskdesk/catalog.json").read_text())
    assert len(catalog["tasks"]) == 40
    assert len(catalog["assignments"]) == 4
    assert all(len(tasks) == len(set(tasks)) == 20 for tasks in catalog["assignments"].values())
    assert set().union(*map(set, catalog["assignments"].values())) == set(catalog["tasks"])
