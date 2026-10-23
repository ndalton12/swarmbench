"""The Antigravity harness in a real container: its own tools, bridged messages, resume, attribution."""

from __future__ import annotations

import pytest

from tests.engine_helpers import (
    info_events,
    make_scenario,
    model_inputs_text,
    requires_docker,
    run_mock,
    span_agents,
)

pytestmark = [requires_docker, pytest.mark.docker]


def test_antigravity_runs_messages_and_resumes_on_wake(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.messaging": "both",
            "advanced.memory_per_agent_mb": 768,
            "advanced.extra": {"harnesses": ["antigravity", "react"], "quiet_period": "12s"},
        },
    )
    scripts = {
        # u01 (Antigravity) works through the SDK's own shell tool, messages u02 over the
        # bridged MCP server, stops, and after waking writes a second file
        "agent-1": [
            ("shell", "echo first > /workspace/u01-first.txt; umask; id -un"),
            ("send", "u02", "hello from u01 via antigravity"),
            ("final", "done for now"),
            ("shell", "echo second > /workspace/u01-second.txt"),
            ("final", "done again"),
        ],
        "agent-2": [
            ("shell", "sleep 14; board post general -m 'u01 please continue'"),
            ("final", "done"),
        ],
    }
    sample, _, mock = run_mock(folder, tmp_path, scripts)

    # the SDK offered its own tools, and MCP tools through its dispatcher
    tools = {t for c in mock.calls if c["agent"] == "agent-1" for t in c["tools"]}
    assert {"run_command", "view_file", "call_mcp_tool"} <= tools, tools
    assert not tools & {"search_web", "read_url_content", "generate_image"}

    # commands ran as u01 with the private umask
    text = model_inputs_text(sample, "agent-1")
    assert "0077" in text and "u01" in text

    # the direct message went out through the bridged tool, from agent-1
    sent = [m for m in sample.store["swarm_messages"] if m["sender"] == "agent-1" and m["channel"] != "board"]
    assert any("hello from u01 via antigravity" in m["text"] for m in sent), sample.store["swarm_messages"]

    # woken by u02's post, it continued the same conversation (the SDK resumed it)
    assert [e for e in info_events(sample, "swarm.agent_wake") if e.data["agent"] == "agent-1"]
    changed = {c["path"] for c in sample.store["swarm_workspace_diff"]["swarm"]["changes"]}
    assert {"/workspace/u01-first.txt", "/workspace/u01-second.txt"} <= changed
    owners = span_agents(sample)
    first_texts = [
        next((m.text for m in e.input if m.role == "user"), "")
        for e in sample.events
        if e.event == "model" and owners.get(e.span_id or "") == "agent-1" and e.input
    ]
    assert first_texts and all("tidying up the notes" in t for t in first_texts)
    assert sample.store["swarm_agent_usage"]["agent-1"]["stop_reason"] == "finished"

    # every request names u01 (its identity line) and joins exactly to the gateway's record
    verdicts = [e.data for e in info_events(sample, "swarm.attribution") if e.data["bridge_of"] == "agent-1"]
    assert verdicts and all(v["verdict"] == "own" for v in verdicts), verdicts
    actors = [a for a in sample.store["swarm_request_actors"].values() if a["bridge_of"] == "agent-1"]
    generated = [a for a in actors if a["generated"]]
    assert len(generated) >= 4, actors
    assert all(a["match"] == "exact" and a["actor"] == "agent-1" for a in generated), generated
    assert not sample.store["swarm_problems"], sample.store["swarm_problems"]


def test_antigravity_background_work_resumes_the_same_session(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 1,
            "swarm.messaging": "board",
            "advanced.memory_per_agent_mb": 768,
            "advanced.extra": {"harnesses": ["antigravity"], "quiet_period": "10s"},
        },
    )
    timer = {"Prompt": "check on the build", "DurationSeconds": "3", "toolSummary": "Timer", "toolAction": "Timer"}
    scripts = {
        # a command longer than run_command's 10 s limit goes to the background; the agent sets
        # a timer and ends its turn, as the SDK tells it to, expecting to be told when they finish
        "agent-1": [
            ("shell", "sleep 13; echo built > /workspace/build.txt"),
            ("tool", "schedule", timer),
            ("final", "waiting for the build"),
        ]
    }
    sample, _, _ = run_mock(folder, tmp_path, scripts)
    text = model_inputs_text(sample, "agent-1")
    # both notices reached the model in the same session, before the agent went to sleep
    assert "finished with result" in text and "check on the build" in text
    assert not info_events(sample, "swarm.agent_wake")
    changed = {c["path"] for c in sample.store["swarm_workspace_diff"]["swarm"]["changes"]}
    assert "/workspace/build.txt" in changed
    assert sample.store["swarm_agent_usage"]["agent-1"]["stop_reason"] == "finished"


def test_antigravity_own_tools_run_commands_and_paper_style_messages(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 2,
            "swarm.harness": "antigravity",
            "swarm.messaging": "direct",
            "swarm.delivery": "on_request",
            "advanced.memory_per_agent_mb": 768,
            "advanced.antigravity_native_tools": True,
            "advanced.direct_messages": {
                "send": {"name": "send_direct_message", "description": "Forwards a direct message to an agent."},
                "read": {"name": "get_messages", "description": "Retrieves all received direct messages."},
                "read_all": True,
                "list_users": False,
                "broadcast": False,
            },
            "advanced.command_tools": [
                {
                    "name": "echo_args",
                    "description": "Echo the arguments back.",
                    "parameters": {"type": "object", "properties": {"note": {"type": "string"}}},
                    "command": ["/bin/sh", "-c", "cat; echo; id -un"],
                }
            ],
            "advanced.extra": {"quiet_period": "10s"},
        },
    )
    scripts = {
        "agent-1": [
            ("tool", "echo_args", {"note": "--hi"}),
            ("send", "u02", "hello from u01"),
            ("final", "done"),
        ],
        "agent-2": [
            ("shell", "sleep 8"),
            ("check",),
            ("check",),
            ("final", "done"),
        ],
    }
    sample, _, mock = run_mock(folder, tmp_path, scripts)

    tools = {t for c in mock.calls if c["agent"] == "agent-1" for t in c["tools"]}
    assert {"echo_args", "send_direct_message", "get_messages"} <= tools, tools
    assert not tools & {"call_mcp_tool", "list_users", "send_message", "check_messages"}
    # the command got the arguments as JSON and ran as the agent
    text = model_inputs_text(sample, "agent-1")
    # (the SDK wraps a tool's output as JSON, so its quotes and newlines arrive escaped)
    plain = text.replace("\\n", "\n").replace("\\", "")
    assert '{"note": "--hi"}\nu01' in plain, plain[-1500:]
    # the bridge ran the proposed message; get_messages showed it on both reads
    assert any(m["text"] == "hello from u01" for m in sample.store["swarm_messages"])
    assert model_inputs_text(sample, "agent-2").count("hello from u01") >= 2
    assert not sample.store.get("swarm_problems")
