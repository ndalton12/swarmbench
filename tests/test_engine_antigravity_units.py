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


def _native_request(groups, descriptions=None):
    return {
        "native_tools": groups,
        "mcp_servers": [{"name": "messages", "url": "http://x/mcp", "headers": {}}],
        "messages_server": "messages",
        "message_descriptions": descriptions or {},
    }


def test_native_tools_offer_the_board_and_messages_as_own_tools(monkeypatch):
    from swarmbench.engine import antigravity_runner as R

    calls = []

    class FakePopen:
        def __init__(self, args, **kw):
            calls.append(args)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def communicate(self, timeout=None):
            return "ok\n", None

    monkeypatch.setattr(R, "_PLAIN_POPEN", FakePopen)
    descriptions = {"send_message": "Send it.", "check_messages": "Check.", "list_users": "Who."}
    tools = {t.__name__: t for t in R.native_tools(_native_request(["board", "messages"], descriptions))}
    assert set(tools) == {"send_message", "check_messages", "list_users", "post_to_board", "read_board"}
    # the SDK describes each tool by its __doc__; message tools carry the bridge's own descriptions
    assert {n: tools[n].__doc__ for n in descriptions} == descriptions
    assert tools["post_to_board"].__doc__ == R.BOARD_DESCRIPTIONS["post_to_board"]
    assert tools["post_to_board"]("general", "--hello") == "ok" and tools["read_board"]() == "ok"
    assert tools["read_board"]("general") == "ok"
    assert calls == [[R.BOARD, "post", "--message=--hello", "--", "general"], [R.BOARD, "read"], [R.BOARD, "read", "--", "general"]]


def test_native_tools_follow_the_team_messaging():
    from swarmbench.engine import antigravity_runner as R
    from swarmbench.engine.harness import native_groups

    assert native_groups(False, board=True, direct=True) == []
    assert native_groups(True, board=True, direct=False) == ["board"]
    assert native_groups(True, board=False, direct=True) == ["messages"]
    assert [t.__name__ for t in R.native_tools(_native_request(["board"]))] == ["post_to_board", "read_board"]
    assert [t.__name__ for t in R.native_tools(_native_request(["messages"]))] == [
        "send_message", "check_messages", "list_users"
    ]


def test_a_board_command_is_not_taken_for_the_agent_engine(tmp_path):
    from swarmbench.engine import antigravity_runner as R

    script = tmp_path / "board"
    script.write_text("#!/bin/sh\necho posted $@\n")
    script.chmod(0o755)
    engines = list(R._engines)
    original = R.subprocess.Popen
    R.subprocess.Popen = R._Popen  # as main() does
    try:
        R.BOARD, board = str(script), R.BOARD
        try:
            assert R._board("post", "general", "-m", "hi") == "posted post general -m hi"
        finally:
            R.BOARD = board
    finally:
        R.subprocess.Popen = original
    assert R._engines == engines  # _settle would read a finished engine as the engine exiting


def test_the_deployed_runner_keeps_the_tool_descriptions():
    from swarmbench.engine.antigravity import runner_source

    namespace: dict = {"__name__": "deployed"}
    exec(compile(runner_source(), "run.py", "exec"), namespace)  # noqa: S102 - our runner, as deployed
    descriptions = {"send_message": "Send it.", "check_messages": "Check.", "list_users": "Who."}
    request = _native_request(["board", "messages"], descriptions)
    tools = {t.__name__: t.__doc__ for t in namespace["native_tools"](request)}
    assert all(tools.values()) and tools["send_message"] == "Send it."


def test_message_tools_are_declared_as_the_bridge_serves_them():
    """The bridge runs a bridged tool only for a call the model proposed, matched by description."""
    from inspect_ai.agent import BridgedToolsSpec
    from inspect_ai.model._call_tools import get_tools_info

    from swarmbench.engine.antigravity import _served_descriptions
    from swarmbench.engine.messages import MessageBus, SwarmLog, message_tools

    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 2}}))
    bus = MessageBus(SwarmLog(), infos)
    tools = message_tools(bus, infos[0].name, via_bridge=True)
    served = _served_descriptions([BridgedToolsSpec(name="messages", tools=tools)], "messages")
    assert served == {i.name: i.description for i in get_tools_info(tools)}
    assert set(served) == {"send_message", "check_messages", "list_users"} and all(served.values())


def test_gemini_tool_declarations_with_upper_case_types_pass_the_bridge():
    from inspect_ai.agent._bridge import google_api_impl

    from swarmbench.engine.geminitools import install

    declaration = {
        "name": "send_message",
        "description": "Send a direct message.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"to": {"type": "STRING"}, "tags": {"type": "ARRAY", "items": {"type": "STRING"}}},
            "required": ["to"],
        },
    }
    assert install()
    (tool,) = google_api_impl.tools_from_google_tools([{"functionDeclarations": [declaration]}], None, None)
    assert tool.name == "send_message" and tool.parameters.type == "object"
    assert tool.parameters.properties["to"].type == "string"
    assert tool.parameters.properties["tags"].items.type == "string"
    assert tool.parameters.required == ["to"]
    assert declaration["parameters"]["type"] == "OBJECT"  # the client's request is left as sent


def test_gemini_type_names_in_literal_data_are_left_alone():
    from swarmbench.engine.geminitools import lowercase_types

    schema = {
        "type": "OBJECT",
        "properties": {
            "type": {"type": "STRING", "enum": ["INVOICE", "RECEIPT"]},
            "doc": {"type": "OBJECT", "default": {"type": "INVOICE"}, "examples": [{"type": "RECEIPT"}]},
            "any": {"anyOf": [{"type": "INTEGER"}, {"type": ["NUMBER", "NULL"]}]},
        },
    }
    out = lowercase_types(schema)
    assert out["type"] == "object" and out["properties"]["type"] == {"type": "string", "enum": ["INVOICE", "RECEIPT"]}
    assert out["properties"]["doc"] == {"type": "object", "default": {"type": "INVOICE"}, "examples": [{"type": "RECEIPT"}]}
    assert out["properties"]["any"]["anyOf"] == [{"type": "integer"}, {"type": ["number", "null"]}]
