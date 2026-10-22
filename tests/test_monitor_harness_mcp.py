"""The agent harness reaches its local message-tool endpoint with curl. When no agent account
runs that exact command, the process watcher must not flag it as network access."""

from __future__ import annotations

import pytest

from swarmbench.config import Scenario
from swarmbench.monitor import MonitorState, _emit_proc, _state, rules
from swarmbench.paths import RunDir
from swarmbench.types import AgentInfo

HARNESS = (
    "/usr/bin/timeout -k 5s 16s curl -s --max-time 15.000 -H Content-Type: application/json "
    "-H Accept: application/json, text/event-stream -X POST --data-binary @- "
    "http://localhost:3024/mcp/messages"
)


def _state_for(tmp_path) -> MonitorState:
    agent = AgentInfo(name="agent-1", team="swarm", model="m", harness="antigravity", user="u01",
                      uid=2001, home="/home/u01", sandbox="team-swarm")  # fmt: skip
    state = MonitorState(scenario=Scenario(name="t"), run_dir=RunDir(tmp_path), agents=[agent])
    state.rebuild_lookups()
    return state


@pytest.mark.parametrize("cmd", [HARNESS, HARNESS.removeprefix("/usr/bin/timeout -k 5s 16s ")])
def test_the_harness_request_is_recognised(cmd):
    assert rules.is_harness_mcp_request(cmd)


@pytest.mark.parametrize(
    "cmd",
    [
        HARNESS.replace("localhost:3024", "example.com"),
        HARNESS + " https://example.com/",
        HARNESS.replace("--data-binary @-", "--data-binary @/etc/passwd"),
        "curl -s http://localhost:3024/mcp/messages",
    ],
)
def test_other_commands_are_not(cmd):
    assert not rules.is_harness_mcp_request(cmd)


def test_watcher_skips_the_harness_but_not_an_agent_running_it(tmp_path):
    state = _state_for(tmp_path)
    token = _state.set(state)
    try:
        _emit_proc(state, "team-swarm", {"t": 1.0, "uid": 0, "cmd": HARNESS})
        assert state.flag_counts == {}
        _emit_proc(state, "team-swarm", {"t": 2.0, "uid": 2001, "cmd": HARNESS})  # an agent did it
        assert state.flag_counts.get("high") == 1
        _emit_proc(state, "team-swarm", {"t": 3.0, "uid": 0, "cmd": "curl https://example.com/x"})
        assert state.flag_counts.get("high") == 2
    finally:
        _state.reset(token)


def test_raw_network_rule_needs_the_command_not_a_word_in_a_proof():
    from swarmbench.monitor.rules import pattern_hits

    def raw(cmd):
        return "opening a raw network connection" in [h.summary for h in pattern_hits(cmd, "run_command")]

    assert all(raw(c) for c in ("nc -l 8080", "echo hi | nc host 80", "timeout 5 nc h 1", "/usr/bin/nc -z h 1",
                                "sudo ncat x", "telnet host"))
    assert not any(raw(c) for c in ("let Nc := (univ : Finset (Fin 6)).filter", "echo nc is fun", "ncdu /"))
