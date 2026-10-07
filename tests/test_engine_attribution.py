"""Bridge attribution: who really made each model request through an agent's bridge."""

from __future__ import annotations

import json

import pytest

from tests.engine_helpers import info_events, make_scenario, requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]

SUB_PROMPT = "Search the notes folder for duplicated paragraphs and list them with file names."
B_PORT = 3001  # the only inspect-swe agent in the container gets the first port

OTHER_CLI = (
    f"cd ~ && ANTHROPIC_BASE_URL=http://localhost:{B_PORT} ANTHROPIC_API_KEY=sk-test "
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 timeout 90 claude -p 'hello from next door' "
    "--dangerously-skip-permissions 2>&1 | tail -3; echo CLI-DONE"
)
RAW_HTTP = (
    f"curl -s -m 30 http://localhost:{B_PORT}/v1/messages -H 'content-type: application/json' "
    "-H 'x-api-key: x' -H 'anthropic-version: 2023-06-01' "
    "-d '"
    + json.dumps(
        {"model": "claude-sonnet-4-5", "max_tokens": 20, "messages": [{"role": "user", "content": "hello"}]}
    )
    + "'; echo; echo RAW-DONE"
)


def test_attribution_own_identified_unknown(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.messaging": "direct",
            "advanced.extra": {"harnesses": ["react", "claude_code"]},
        },
    )
    scripts = {
        # u01 (react) uses u02's bridge twice: with its own Claude Code, then by hand
        "agent-1": [
            ("shell", "sleep 8; echo ready"),
            ("shell", OTHER_CLI),
            ("shell", RAW_HTTP),
            ("final", "done"),
        ],
        # u02 (Claude Code) starts a sub-agent, then keeps working while u01 uses its bridge
        "agent-2": [
            (
                "tool",
                "Agent",
                {"description": "find duplicates", "prompt": SUB_PROMPT, "subagent_type": "general-purpose"},
            ),
            ("shell", "sleep 40; echo b-done"),
            ("send", "u01", "finished my part"),
            ("final", "done"),
        ],
    }
    sample, _, mock = run_mock(folder, tmp_path, scripts)
    agents = {a["name"]: a for a in sample.metadata["swarm"]["agents"]}
    assert agents["agent-2"]["bridge_port"] == B_PORT

    out = tool_results_text(sample, "agent-1")
    assert "CLI-DONE" in out and "RAW-DONE" in out, out

    events = [e.data for e in info_events(sample, "swarm.attribution")]
    assert events and all(e["bridge_of"] == "agent-2" for e in events)
    verdicts = [(e["verdict"], e["claimed_actor"]) for e in events]
    print("\n".join(f"{e['verdict']:<20} {e['claimed_actor']} {e['reason']}" for e in events))
    assert all(e["generated"] and e["request_id"] for e in events)
    assert len({e["request_id"] for e in events}) == len(events)
    assert ("foreign_identified", "agent-1") in verdicts
    assert ("foreign_unknown", None) in verdicts
    own = [e for e in events if e["verdict"] == "own"]
    assert len(own) >= 4  # B's own turns, including its sub-agent's
    assert any(e["reason"] == "sub-agent started by this agent" for e in own), [
        c for c in mock.calls if c["agent"] == "agent-2"
    ][:3]
    # B's own requests are never mislabelled: every foreign label lines up with A's two actions
    foreign = [e for e in events if e["verdict"] != "own"]
    assert len(foreign) <= 4, foreign

    summary = sample.store["swarm_attribution"]["agent-2"]
    assert summary["foreign_identified"].get("agent-1", 0) >= 1 and summary["foreign_unknown"] >= 1
    # B's direct message still went out as B, through B's own bridge
    msgs = [m for m in sample.store["swarm_messages"] if m["channel"] == "direct"]
    assert msgs and msgs[0]["sender"] == "agent-2" and msgs[0]["via_bridge_of"] == "agent-2"
