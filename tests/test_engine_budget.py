"""Per-agent budgets: when one agent runs out, only that agent stops."""

from __future__ import annotations

import pytest

from tests.engine_helpers import info_events, make_scenario, requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]


def _stopped(sample) -> dict[str, str]:
    return {e.data["agent"]: e.data["reason"] for e in info_events(sample, "swarm.agent_stopped")}


def test_react_budget_stops_only_that_agent(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{"swarm.agents": 2, "swarm.token_budget": 8000, "swarm.messaging": "off", "advanced.extra": {}},
    )
    long_script = [("shell", f"echo step {i}; " + "x" * 400) for i in range(40)] + [("final", "done")]
    slow_script = [("shell", "sleep 4; echo slow-1"), ("shell", "sleep 4; echo slow-2"), ("final", "done")]
    sample, _, _ = run_mock(folder, tmp_path, {"agent-1": long_script, "agent-2": slow_script})

    stopped = _stopped(sample)
    usage = sample.store["swarm_agent_usage"]
    assert stopped == {"agent-1": "budget", "agent-2": "finished"}, (stopped, usage)
    assert usage["agent-1"]["stop_reason"] == "budget"
    assert usage["agent-1"]["tokens"] >= 4000
    # agent-2 kept going after agent-1 ran out
    assert "slow-2" in tool_results_text(sample, "agent-2")
    assert sample.error is None


def test_bridge_budget_stops_claude_code_only(tmp_path):
    # Claude Code's first call alone is ~15k tokens (its system prompt), so 45k per agent
    # lets it make a couple of calls; the react agent needs far less.
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.token_budget": 90000,
            "swarm.messaging": "off",
            "advanced.extra": {"harnesses": ["react", "claude_code"]},
        },
    )
    react_script = [("shell", f"sleep 2; echo react-{i}") for i in range(8)] + [("final", "done")]
    claude_script = [("shell", f"echo claude-{i}") for i in range(10)] + [("final", "done")]
    sample, _, mock = run_mock(folder, tmp_path, {"agent-1": react_script, "agent-2": claude_script})

    stopped = _stopped(sample)
    usage = sample.store["swarm_agent_usage"]
    assert stopped["agent-2"] == "budget", (stopped, usage)
    assert stopped["agent-1"] == "finished"
    assert "react-7" in tool_results_text(sample, "agent-1")
    claude_calls = [c for c in mock.calls if c["agent"] == "agent-2" and c["tools"]]
    assert 1 <= len(claude_calls) < 10
    # each call reserves its estimate before it is sent, so the budget is never overshot
    assert 15000 <= usage["agent-2"]["tokens"] <= 45000
    refused = [e.data for e in info_events(sample, "swarm.attribution") if not e.data["generated"]]
    assert refused and all(e["bridge_of"] == "agent-2" for e in refused)
    # every generated request's model event carries its request id
    ids = {e.data["request_id"] for e in info_events(sample, "swarm.attribution") if e.data["generated"]}
    tagged = {
        e.input[-1].metadata.get("swarm_request_id")
        for e in sample.events
        if e.event == "model" and e.input and e.input[-1].metadata
    }
    assert ids and ids <= tagged
