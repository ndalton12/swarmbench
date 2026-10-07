from pathlib import Path

import pytest

from swarmbench.config import load_scenario, parse_count, parse_duration


def write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "scenario.yaml").write_text(text)
    return tmp_path


def test_parsers():
    assert parse_count("2M") == 2_000_000
    assert parse_count("500k") == 500_000
    assert parse_duration("90m") == 5400


def test_single_team_defaults(tmp_path):
    s = load_scenario(write(tmp_path, "name: x\nswarm: {agents: 3, messaging: true}\n"))
    (team,) = s.resolved_teams()
    assert team.name == "swarm" and team.messaging == "direct"
    assert team.agent_names() == ["agent-1", "agent-2", "agent-3"]


def test_teams_and_overrides(tmp_path):
    s = load_scenario(
        write(
            tmp_path,
            "name: x\nswarm: {agents: 2}\nteams: [{name: red}, {name: blue, agents: 3}]\n"
            "encounter: {after: 30m, via: board_channel, path: commons}\n",
        ),
        {"swarm.agents": 4, "swarm.effort": "high"},
    )
    red, blue = s.resolved_teams()
    assert red.agents == 4 and blue.agents == 3 and red.effort == "high"
    assert blue.agent_names()[0] == "blue-agent-1"


def test_encounter_needs_two_teams(tmp_path):
    with pytest.raises(ValueError):
        load_scenario(write(tmp_path, "name: x\nencounter: {after: 1m}\n"))
