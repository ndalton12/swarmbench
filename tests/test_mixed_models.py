"""Several models in one team (``swarm.models``): config, overrides, costs, agents and the judge."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from swarmbench import costs
from swarmbench.config import Scenario, load_scenario
from swarmbench.engine.layout import agent_infos
from swarmbench.judge.two_pass import mixed_models, models_note
from tests.engine_helpers import make_scenario, requires_docker, run_mock

A, B = "openrouter/google/gemini-3.1-pro-preview", "openrouter/google/gemini-4-argon"


def scenario(**swarm) -> Scenario:
    return Scenario.model_validate({"name": "mix", "swarm": {"agents": 4, **swarm}})


def test_models_are_given_out_in_turn():
    s = scenario(models=[A, B])
    (team,) = s.resolved_teams()
    assert team.agent_models() == [A, B, A, B]
    assert team.model == A
    assert [a.model for a in agent_infos(s)] == [A, B, A, B]
    assert s.agent_models() == [A, B]


def test_one_model_is_unchanged():
    s = scenario(model=A)
    assert [a.model for a in agent_infos(s)] == [A] * 4
    assert s.agent_models() == [A]


@pytest.mark.parametrize("swarm", [{"models": []}, {"models": [A, " "]}])
def test_bad_model_settings(swarm):
    with pytest.raises(ValidationError):
        scenario(**swarm)


def test_a_scenario_file_may_not_set_both(tmp_path):
    folder = make_scenario(tmp_path, **{"swarm.model": A, "swarm.models": [A, B]})
    with pytest.raises(ValueError, match="both model and models"):
        load_scenario(folder)


def test_the_recorded_scenario_loads_again(tmp_path):
    from swarmbench.config import dump_scenario

    (tmp_path / "scenario.yaml").write_text(dump_scenario(scenario(models=[A, B])))
    assert load_scenario(tmp_path).agent_models() == [A, B]


def test_dry_run_replaces_every_model_with_the_mock():
    from swarmbench.engine.dryrun import MOCK_MODEL, dry_run_scenario

    s = Scenario.model_validate(
        {
            "name": "mix",
            "swarm": {"agents": 2, "models": [A, B]},
            "teams": [{"name": "red"}, {"name": "blue", "models": [B, A]}],
        }
    )
    assert set(dry_run_scenario(s).agent_models()) == {MOCK_MODEL}
    # the dumped copy validates again (models replace model, so no conflict)
    assert Scenario.model_validate(s.model_dump(mode="json")).agent_models() == [A, B]


def test_teams_inherit_or_replace_the_mix():
    s = Scenario.model_validate(
        {
            "name": "mix",
            "swarm": {"agents": 2, "models": [A, B]},
            "teams": [{"name": "red"}, {"name": "blue", "model": B}, {"name": "green", "models": [B, A]}],
        }
    )
    red, blue, green = s.resolved_teams()
    assert red.agent_models() == [A, B]
    assert blue.agent_models() == [B, B]
    assert green.agent_models() == [B, A]
    with pytest.raises(ValidationError):
        Scenario.model_validate({"name": "mix", "teams": [{"name": "red", "model": A, "models": [B]}]})


def test_command_line_model_replaces_a_mix(tmp_path):
    folder = make_scenario(tmp_path, **{"swarm.models": [A, B], "advanced.extra": {}})
    data = yaml.safe_load((folder / "scenario.yaml").read_text())
    data["swarm"].pop("model", None)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(data))
    assert load_scenario(folder).agent_models() == [A, B]
    assert load_scenario(folder, {"swarm.model": B}).agent_models() == [B]


def test_estimate_prices_each_agent_at_its_own_model():
    prices = {A: costs.ModelCost(input=1, output=10, input_cache_write=1, input_cache_read=0.1),
              B: costs.ModelCost(input=1, output=20, input_cache_write=1, input_cache_read=0.1)}  # fmt: skip
    s = scenario(models=[A, B], token_budget="4M")
    est = costs.estimate_max_cost(s, prices)
    # 1M tokens per agent: two agents at $10/M, two at $20/M
    assert est.swarm_per_epoch == pytest.approx(60.0)
    assert f"2 x {A} + 2 x {B}" in est.lines[0]


def test_judge_is_blind_to_models_only_when_they_differ():
    mixed = [{"name": "agent-1", "model": A, "user": "u01"}, {"name": "agent-2", "model": B, "user": "u02"}]
    same = [{"name": "agent-1", "model": A}, {"name": "agent-2", "model": A}]
    assert mixed_models(mixed) == {"agent-1": A, "agent-2": B}
    assert mixed_models(same) == {}
    note = models_note(mixed)
    assert note and f"agent-1: {A}" in note and f"agent-2: {B}" in note
    assert models_note(same) is None


def test_run_brief_leaves_out_models_in_a_mixed_run():
    from types import SimpleNamespace

    from swarmbench.judge.two_pass import run_brief

    def brief(meta):
        inputs = SimpleNamespace(agents_meta=meta, agents=[], scenario="mix")
        return run_brief(SimpleNamespace(events=[]), inputs, "")

    mixed = [{"name": "agent-1", "model": A, "user": "u01"}, {"name": "agent-2", "model": B, "user": "u02"}]
    text = brief(mixed)
    assert "u01" in text and A not in text and B not in text
    assert A in brief([{"name": "agent-1", "model": A, "user": "u01"}])


@pytest.mark.docker
@requires_docker
def test_a_mixed_team_runs(tmp_path):
    folder = make_scenario(tmp_path, **{"swarm.agents": 2, "swarm.models": [A, B], "advanced.extra": {}})
    data = yaml.safe_load((folder / "scenario.yaml").read_text())
    data["swarm"].pop("model", None)
    (folder / "scenario.yaml").write_text(yaml.safe_dump(data))
    sample, _, _ = run_mock(
        folder, tmp_path, {"agent-1": [("final", "done")], "agent-2": [("final", "done")]}
    )
    # a dry run of a mixed team runs every agent on the mock model, never a real one
    agents = sample.metadata["swarm"]["agents"]
    assert [a["model"] for a in agents] == ["mockllm/model"] * 2


def test_command_line_list_of_models(tmp_path):
    from swarmbench.cli import model_flags
    from swarmbench.runner.runs import resolve

    assert model_flags(f"{A}, {B}") == {"swarm.models": [A, B]}
    assert model_flags(A) == {"swarm.model": A}
    folder = make_scenario(tmp_path, **{"swarm.model": A})
    resolved, _ = resolve(folder, model_flags(f"{A},{B}"))
    assert resolved.agent_models() == [A, B]


def test_command_line_model_reaches_every_team(tmp_path):
    from swarmbench.runner.runs import resolve

    folder = make_scenario(tmp_path, teams=[{"name": "red", "models": [A, B]}, {"name": "blue", "model": A}])
    resolved, _ = resolve(folder, {"swarm.model": B})
    assert resolved.agent_models() == [B]
    resolved, _ = resolve(folder, {"swarm.models": [B, A]})
    assert [t.agent_models()[:2] for t in resolved.resolved_teams()] == [[B, A], [B, A]]
