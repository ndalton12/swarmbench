"""The request gateway: every bridge request is attributed to the uid that made it,
and no non-root process can reach a bridge without the gateway seeing it."""

from __future__ import annotations

import json

import pytest

from tests.engine_helpers import info_events, make_scenario, requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]

B_PORT = 3001  # the single inspect-swe agent's bridge
FRONT = B_PORT + 1000

# A raw request to a given port, as agent u01, using bash's own /dev/tcp.
RAW = (
    "exec 3<>/dev/tcp/127.0.0.1/{port} && "
    "printf 'POST /v1/messages HTTP/1.1\\r\\nHost: x\\r\\nContent-Length: 7\\r\\n\\r\\nhello!!' >&3 && "
    "timeout 3 cat <&3 >/dev/null; echo DONE-{tag}"
)


def test_gateway_attributes_and_blocks_bypass(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.messaging": "off",
            "advanced.extra": {"harnesses": ["react", "claude_code"]},
        },
    )
    scripts = {
        # u01 pokes u02's bridge directly (real port) and via the front port
        "agent-1": [
            ("shell", "sleep 8"),
            ("shell", RAW.format(port=B_PORT, tag="real")),
            ("shell", RAW.format(port=FRONT, tag="front")),
            # it also can't reach the bridge over a port root uses, unseen: everything it does is logged
            ("final", "done"),
        ],
        "agent-2": [("shell", "sleep 25; echo b"), ("final", "done")],
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)
    agents = {a["name"]: a for a in sample.metadata["swarm"]["agents"]}
    assert agents["agent-2"]["bridge_port"] == B_PORT

    out = tool_results_text(sample, "agent-1")
    assert "DONE-real" in out and "DONE-front" in out  # both connections reached the gateway

    records = sample.store["swarm_bridge_requests"]
    reqs = [r for r in records if r["t"] == "request"]
    # u02's own model calls are attributed to uid 2002
    own = [r for r in reqs if r["uid"] == 2002]
    assert own and all(r["bridge_port"] == B_PORT for r in own)
    # u01's two raw pokes are attributed to uid 2001, not u02 -- it cannot borrow the bridge unseen
    foreign = [r for r in reqs if r["uid"] == 2001]
    assert len(foreign) >= 2, [r for r in reqs]
    assert all(r.get("body_sha256") for r in foreign)
    # the connection records cover both the real and the front port (both reached the gateway)
    conns = [c for c in records if c["t"] == "connect" and c["uid"] == 2001]
    assert {c["bridge_port"] for c in conns} == {B_PORT}  # real-port connects are redirected to the gateway
    print(json.dumps(foreign[0], indent=2))

    # every model request u02's bridge generated joins exactly to a gateway record (by body
    # digest), and the gateway names u02 as the real sender
    actors = sample.store["swarm_request_actors"]
    generated = [a for a in actors.values() if a["generated"] and a["bridge_of"] == "agent-2"]
    assert generated, actors
    assert all(a["match"] == "exact" and a["actor"] == "agent-2" for a in generated), generated
    # records were collected during the run and kept on the host too
    assert not any("gateway" in p for p in sample.store["swarm_problems"]), sample.store["swarm_problems"]


def test_gateway_death_is_detected_and_reported(tmp_path):
    import anyio

    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.messaging": "off",
            "advanced.extra": {"harnesses": ["react", "claude_code"], "quiet_period": "15s"},
        },
    )

    def on_start(swarm):  # the gateway process dies a few seconds into the run
        async def kill_gateway() -> None:
            await anyio.sleep(4)
            rt = swarm.teams[0]
            await rt.sandbox.exec(["/usr/bin/pkill", "-KILL", "-f", "svcgwd"], user="root")

        swarm.background.start_soon(kill_gateway)

    scripts = {"agent-1": [("shell", "sleep 2"), ("final", "done")], "agent-2": [("final", "done")]}
    sample, _, _ = run_mock(folder, tmp_path, scripts, on_start=on_start)

    problems = sample.store["swarm_problems"]
    assert any("request gateway for team swarm stopped" in p for p in problems), problems
    assert [e.data["team"] for e in info_events(sample, "swarm.gateway_down")] == ["swarm"]
    outcome = sample.metadata["swarm_outcome"]
    assert outcome["outcome"] == "gateway_down" and not outcome["ok"]
