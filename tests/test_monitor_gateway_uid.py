"""The request gateway runs as root and forwards to the real bridge ports; its connections
must never be flagged as one agent using another's bridge."""

from swarmbench.config import Scenario
from swarmbench.monitor import MonitorState, _emit_bridge, _state
from swarmbench.paths import RunDir
from swarmbench.types import AgentInfo


def _state_for(tmp_path):
    agents = [
        AgentInfo(
            name=f"agent-{i}",
            team="swarm",
            model="m",
            harness="claude_code",
            user=f"u0{i}",
            uid=2000 + i,
            home=f"/home/u0{i}",
            sandbox="team-swarm",
            bridge_port=3000 + i,
        )
        for i in (1, 2)
    ]
    state = MonitorState(scenario=Scenario(name="t"), run_dir=RunDir(tmp_path), agents=agents)
    state.rebuild_lookups()
    return state


def test_root_gateway_connections_are_not_flagged(tmp_path):
    state = _state_for(tmp_path)
    token = _state.set(state)
    try:
        _emit_bridge(state, "team-swarm", {"t": 1.0, "port": 3001, "peer_uid": 0, "state": "open"})
        assert state.flag_counts == {}
        assert state.bridge_summary == {}
        assert state.bridge_intervals == {}
        # an agent using another agent's bridge is still flagged
        _emit_bridge(state, "team-swarm", {"t": 2.0, "port": 3001, "peer_uid": 2002, "state": "open"})
        assert state.flag_counts == {"high": 1}
        assert state.bridge_summary == {"agent-1": {"agent-2": 1}}
    finally:
        _state.reset(token)
