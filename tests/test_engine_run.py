"""End-to-end mock runs: the phase-1 slice, live status, and a clean stop."""

from __future__ import annotations

import json
import time

import anyio
import pytest

from swarmbench.paths import RunDir
from swarmbench.status import read_status
from tests.engine_helpers import (
    info_events,
    make_scenario,
    model_inputs_text,
    requires_docker,
    run_mock,
    span_agents,
    tool_results_text,
)

pytestmark = [requires_docker, pytest.mark.docker]


def test_slice_react_and_claude_code_with_board_and_direct_messages(tmp_path):
    """Two agents (react + Claude Code) in one container, default mock scripts."""
    folder = make_scenario(tmp_path)  # 2 agents, messaging both, harnesses react + claude_code
    sample, run_dir, _ = run_mock(folder, tmp_path)

    # every agent has its own span, and its model calls land there
    owners = span_agents(sample)
    model_spans = {owners.get(e.span_id) for e in sample.events if e.event == "model"}
    assert {"agent-1", "agent-2"} <= model_spans

    stopped = {e.data["agent"]: e.data["reason"] for e in info_events(sample, "swarm.agent_stopped")}
    assert stopped == {"agent-1": "finished", "agent-2": "finished"}

    messages = sample.store["swarm_messages"]
    direct = [m for m in messages if m["channel"] == "direct"]
    board = [m for m in messages if m["channel"] == "board"]
    assert {m["sender"] for m in direct} == {"agent-1", "agent-2"}
    assert {m["sender"] for m in board} == {"agent-1", "agent-2"}  # sender from file owner
    assert all(m["board_channel"] == "general" for m in board)
    # each agent was shown the other's direct message (check_messages or a notice digest)
    for m in direct:
        assert m["read_by"] == m["delivered_to"], m
    # board reads come from ~/.board_seen
    assert any(m["read_by"] for m in board)
    assert len(info_events(sample, "swarm.message")) == len(messages)
    assert info_events(sample, "swarm.read")

    usage = sample.store["swarm_agent_usage"]
    assert set(usage) == {"agent-1", "agent-2"} and all(u["tokens"] > 0 for u in usage.values())
    assert sample.store["swarm_problems"] == []
    agents = {a["name"]: a for a in sample.metadata["swarm"]["agents"]}
    assert agents["agent-1"]["bridge_port"] is None and agents["agent-2"]["bridge_port"] == 3001

    # the seeded ops post is scenery, not a message, but agents can read it
    assert "ops  #general" in tool_results_text(sample, "agent-1")
    # the claude code agent got its peer's message as a notice in its conversation
    assert "[new messages]" in model_inputs_text(sample, "agent-2")

    # run folder
    assert run_dir.provenance.exists() and run_dir.scenario.exists()
    prov = json.loads(run_dir.provenance.read_text())
    assert prov["images"][0]["id"].startswith("sha256:") and prov["versions"]["inspect_ai"]
    status = read_status(run_dir)
    assert status is not None and status.agents_total == 2 and status.messages == len(messages)
    assert status.compose_project and status.swarm_cost.tokens > 0


def test_stop_request_winds_down_cleanly(tmp_path):
    folder = make_scenario(tmp_path, **{"swarm.messaging": "off"})
    slow = [("shell", f"sleep 3; echo tick-{i}") for i in range(30)] + [("final", "done")]

    def on_start(swarm):
        async def request_stop_later() -> None:
            await anyio.sleep(8)
            (RunDir(swarm.run_dir.root).root / "stop_requested").write_text("stopped by swarm stop")

        swarm.background.start_soon(request_stop_later)

    started = time.monotonic()
    sample, _run_dir, _ = run_mock(folder, tmp_path, {"agent-1": slow, "agent-2": slow}, on_start=on_start)
    elapsed = time.monotonic() - started

    assert elapsed < 30 * 3, elapsed  # well before the scripts would have finished
    assert "run stopped early: stopped by swarm stop" in sample.store["swarm_problems"]
    assert [e.data["reason"] for e in info_events(sample, "swarm.stop")] == ["stopped by swarm stop"]
    stopped = {e.data["agent"]: e.data["reason"] for e in info_events(sample, "swarm.agent_stopped")}
    assert stopped == {"agent-1": "stopped", "agent-2": "stopped"}, stopped
    # the log is complete: the sample finished normally and the store was written
    assert "swarm_messages" in sample.store and "swarm_agent_usage" in sample.store
    assert "tick-29" not in tool_results_text(sample, "agent-1")
