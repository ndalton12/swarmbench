"""The Antigravity harness without Docker: wiring, the in-container runner's checks, mock tools."""

from __future__ import annotations

from typing import Any

import pytest
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.tool import ToolCall, ToolInfo, ToolParams
from inspect_ai.tool._tool_params import ToolParam

from swarmbench.config import Scenario
from swarmbench.engine import antigravity_runner as runner
from swarmbench.engine.bodyhash import canonical_json_sha256, request_digest
from swarmbench.engine.compose import MEMORY_PER_AGENT_MB, team_limits
from swarmbench.engine.harness import build_agent
from swarmbench.engine.layout import agent_infos
from swarmbench.engine.mock import _message_call, _progress, _shell_call
from swarmbench.engine.ports import STORE_KEYS


def scenario(**swarm: Any) -> Scenario:
    return Scenario.model_validate({"name": "ag", "swarm": {"agents": 2, "harness": "antigravity", **swarm}})


def build(sc: Scenario, monkeypatch: pytest.MonkeyPatch, dry_model: Any = None) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "agent"

    monkeypatch.setattr("swarmbench.engine.antigravity.antigravity", fake)
    info = agent_infos(sc)[0]
    build_agent(
        info,
        sc.resolved_teams()[0],
        hostname="research-ws4",
        bus=None,
        direct=False,
        notice=False,
        should_stop=lambda: False,
        bridge_filter=None,
        compaction=False,
        dry_model=dry_model,
    )
    return captured


def test_scenario_accepts_antigravity_and_sizes_its_container():
    sc = scenario()
    assert {a.harness for a in agent_infos(sc)} == {"antigravity"}
    assert team_limits(sc, 0)["mem_limit"] == f"{1024 + 2 * MEMORY_PER_AGENT_MB['antigravity']}m"
    assert STORE_KEYS["antigravity"] == "antigravity_bridge_port"


def test_build_agent_passes_identity_effort_and_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")  # the client is built, never called
    sc = scenario(model="openrouter/google/gemini-3.1-pro-preview", effort="high")
    args = build(sc, monkeypatch)
    assert args["system_prompt"] == "Your account on research-ws4 is u01; your home directory is /home/u01."
    assert args["user"] == "u01" and args["home"] == "/home/u01" and args["cwd"] == "/workspace"
    assert args["env"]["HOME"] == "/home/u01" and "BASH_ENV" in args["env"]
    assert args["effort"] == "high" and args["endpoint_model"] == "gemini-3.1-pro-preview"
    # effort reaches the provider through the model's own config (the bridge drops the SDK's)
    assert str(args["model"]) == "openrouter/google/gemini-3.1-pro-preview"
    assert args["model"].config.reasoning_effort == "high"


def test_build_agent_uses_the_task_model_in_dry_runs(monkeypatch):
    args = build(scenario(model="openrouter/google/gemini-3.1-pro-preview"), monkeypatch, dry_model=object())
    assert args["model"] is None


def test_google_request_digest_ignores_the_model_the_proxy_adds():
    body = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}], "generationConfig": {"topK": 50}}
    assert request_digest("inspect_google_api_request", {**body, "model": "gemini"}) == canonical_json_sha256(body)
    # other wire formats carry the model in the body the client sent
    anthropic = {"model": "claude", "messages": []}
    assert request_digest("inspect_anthropic_api_request", anthropic) == canonical_json_sha256(anthropic)


# Task logs as the pinned engine (google-antigravity 0.1.7) writes them.
TIMER = "Successfully scheduled one-shot timer.\nExpected to fire at: 2026-10-15T22:13:54Z\nPrompt: p\n\n"
CRON = "Successfully scheduled cron job.\nCron Expression: * * * * *\nNext fire time: 2026-10-15T22:14:00Z\n\n"


def test_runner_knows_which_timers_are_still_due():
    assert runner._timer_pending(TIMER)
    assert not runner._timer_pending(TIMER + "[2026-10-15T22:13:54Z] Timer fired.\n")
    assert not runner._timer_pending(TIMER + "[x] Timer cancelled: agent received a message during wait.\n")
    assert runner._timer_pending(CRON)
    fired = CRON + "[t] Cron triggered (iteration 1).\n"
    assert runner._timer_pending(fired + "[t] Next scheduled fire time: 2026-10-15T22:15:00Z\n")
    assert not runner._timer_pending(fired)  # its last iteration
    assert not runner._timer_pending("some other task log\n")
    # the prompt is the model's own text, not the engine's status
    tricky = TIMER.replace("Prompt: p", "Prompt: see if the build was cancelled.\nTimer fired.")
    assert runner._timer_pending(tricky)


def _tool(name: str, *params: str) -> ToolInfo:
    return ToolInfo(
        name=name,
        description=name,
        parameters=ToolParams(properties={p: ToolParam(type="string") for p in params}, required=list(params)),
    )


def test_mock_drives_antigravity_tools():
    tools = [
        _tool("run_command", "CommandLine", "Cwd", "WaitMsBeforeAsync", "toolSummary", "toolAction"),
        _tool("call_mcp_tool", "ServerName", "ToolName", "Arguments", "toolSummary", "toolAction"),
    ]
    name, args = _shell_call(tools, "id")  # type: ignore[misc]
    assert name == "run_command" and args["CommandLine"] == "id" and args["Cwd"] == "/workspace"
    name, args = _message_call(tools, "send_message", {"to": "u02", "text": "hi"})  # type: ignore[misc]
    assert name == "call_mcp_tool"
    assert args["ServerName"] == "messages" and args["ToolName"] == "send_message"
    assert args["Arguments"] == {"to": "u02", "text": "hi"}
    # a wake note arrives wrapped in the SDK's request tags and still counts as progress
    wrapped = "<USER_REQUEST>\n[activity on this host]\nu02 posted in #general: hi\n</USER_REQUEST>"
    call = ToolCall(id="c1", function="run_command", arguments={})
    msgs = [ChatMessageUser(content="task"), ChatMessageAssistant(content="", tool_calls=[call])]
    assert _progress([*msgs, ChatMessageUser(content=wrapped)]) == 2


def test_runner_copied_into_the_home_has_no_notes_about_the_setup():
    from swarmbench.engine.antigravity import runner_source

    source = runner_source()
    compile(source, "run.py", "exec")
    assert "def _settle" in source and "DISABLED_TOOLS" in source
    for word in ("swarm", "harness", "container", "test", "inspect"):
        assert word not in source.lower(), word
