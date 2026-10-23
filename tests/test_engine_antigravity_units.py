"""The Antigravity harness without Docker: wiring, the in-container runner's checks, mock tools."""

from __future__ import annotations

from typing import Any

import pytest
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser
from inspect_ai.tool import ToolCall, ToolDef, ToolInfo, ToolParams
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


@pytest.fixture
def sdk_tools(monkeypatch):
    """A stand-in for the SDK's ToolWithSchema (the SDK itself only exists in the image)."""
    import sys
    import types

    class ToolWithSchema:
        def __init__(self, fn, input_schema):
            self.fn, self.input_schema = fn, input_schema
            self.__name__, self.__doc__ = fn.__name__, fn.__doc__

        def __call__(self, **kwargs):
            return self.fn(**kwargs)

    module = types.ModuleType("google.antigravity.tools.tool_runner")
    module.ToolWithSchema = ToolWithSchema
    for name in ("google", "google.antigravity", "google.antigravity.tools"):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "google.antigravity.tools.tool_runner", module)
    return ToolWithSchema


SCHEMA = {"type": "object", "properties": {"intent_type": {"type": "string"}, "content": {"type": "string"}}}


def _native_request(tmp_path, message_tools=(), script="cat"):
    tool = tmp_path / "tool"
    tool.write_text(f"#!/bin/sh\n{script}\n")
    tool.chmod(0o755)
    return {
        "mcp_servers": [{"name": "messages", "url": "http://x/mcp", "headers": {}}],
        "messages_server": "messages",
        "message_tools": list(message_tools),
        "command_tools": [
            {"name": "post_intent", "description": "Post it.", "parameters": SCHEMA, "command": [str(tool)], "timeout": 5}
        ],
    }


def test_native_tools_are_the_message_and_command_tools_with_their_schemas(sdk_tools, tmp_path):
    from swarmbench.engine import antigravity_runner as R

    send = {"name": "send_direct_message", "description": "Forwards a direct message to an agent.",
            "parameters": {"type": "object", "properties": {"to": {"type": "string"}}}}
    tools = {t.__name__: t for t in R.native_tools(_native_request(tmp_path, [send]))}
    assert set(tools) == {"send_direct_message", "post_intent"}
    assert tools["send_direct_message"].__doc__ == "Forwards a direct message to an agent."
    assert tools["send_direct_message"].input_schema == send["parameters"]
    assert tools["post_intent"].__doc__ == "Post it." and tools["post_intent"].input_schema == SCHEMA


def test_a_command_tool_gets_its_arguments_as_json_without_the_sdk_fields(sdk_tools, tmp_path):
    import json

    from swarmbench.engine import antigravity_runner as R

    (post,) = R.native_tools(_native_request(tmp_path))
    out = post(intent_type="exploring", content="-- hi", toolAction="Posting", toolSummary="Post")
    assert json.loads(out) == {"intent_type": "exploring", "content": "-- hi"}


def test_a_command_tool_reports_failure_and_timeouts(sdk_tools, tmp_path):
    from swarmbench.engine import antigravity_runner as R

    (fails,) = R.native_tools(_native_request(tmp_path, script="echo bad intent; exit 2"))
    assert fails(intent_type="x") == "error (exit 2): bad intent"
    request = _native_request(tmp_path, script="sleep 5")
    request["command_tools"][0]["timeout"] = 0.2
    (slow,) = R.native_tools(request)
    assert slow() == "error: no answer after 0 seconds"


def test_a_command_tool_timeout_ends_everything_it_started(sdk_tools, tmp_path):
    import time

    from swarmbench.engine import antigravity_runner as R

    request = _native_request(tmp_path, script="sleep 30 & sleep 30; echo done")
    request["command_tools"][0]["timeout"] = 0.5
    (slow,) = R.native_tools(request)
    start = time.monotonic()
    assert slow().startswith("error: no answer after")
    assert time.monotonic() - start < 5  # not held open by the background child


def test_a_command_tool_is_not_taken_for_the_agent_engine(sdk_tools, tmp_path):
    from swarmbench.engine import antigravity_runner as R

    (post,) = R.native_tools(_native_request(tmp_path, script="echo posted"))
    engines = list(R._engines)
    original = R.subprocess.Popen
    R.subprocess.Popen = R._Popen  # as main() does
    try:
        assert post(intent_type="exploring") == "posted"
    finally:
        R.subprocess.Popen = original
    assert R._engines == engines  # _settle would read a finished engine as the engine exiting


def test_the_deployed_runner_keeps_the_tool_descriptions(sdk_tools, tmp_path):
    from swarmbench.engine.antigravity import runner_source

    namespace: dict = {"__name__": "deployed"}
    exec(compile(runner_source(), "run.py", "exec"), namespace)  # noqa: S102 - our runner, as deployed
    send = {"name": "get_messages", "description": "Retrieves all received direct messages.", "parameters": {}}
    tools = {t.__name__: t.__doc__ for t in namespace["native_tools"](_native_request(tmp_path, [send]))}
    assert tools == {"get_messages": "Retrieves all received direct messages.", "post_intent": "Post it."}


def _paper_messages():
    from swarmbench.config import DirectMessages

    return DirectMessages.model_validate(
        {
            "send": {"name": "send_direct_message", "description": "Forwards a direct message to an agent."},
            "read": {"name": "get_messages", "description": "Retrieves all received direct messages."},
            "read_all": True,
            "list_users": False,
            "broadcast": False,
            "wake_preview": False,
        }
    )


def test_message_tools_are_declared_as_the_bridge_serves_them():
    """The bridge runs a bridged tool only for a call the model proposed, matched by description."""
    from inspect_ai.agent import BridgedToolsSpec
    from inspect_ai.model._call_tools import get_tools_info

    from swarmbench.engine.antigravity import _served_tools
    from swarmbench.engine.messages import MessageBus, SwarmLog, message_tools

    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 2}}))
    tools = message_tools(MessageBus(SwarmLog(), infos), infos[0].name, via_bridge=True, settings=_paper_messages())
    served = _served_tools([BridgedToolsSpec(name="messages", tools=tools)], "messages")
    assert [(t["name"], t["description"]) for t in served] == [
        (i.name, i.description) for i in get_tools_info(tools)
    ] == [
        ("send_direct_message", "Forwards a direct message to an agent."),
        ("get_messages", "Retrieves all received direct messages."),
    ]
    assert set(served[0]["parameters"]["properties"]) == {"to", "text"}


def test_paper_style_messages_keep_history_go_to_one_colleague_and_name_them():
    import anyio
    from inspect_ai.tool import ToolError

    from swarmbench.engine.messages import MessageBus, SwarmLog, message_tools

    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 3}}))
    bus = MessageBus(SwarmLog(), infos)
    send1, _ = message_tools(bus, "agent-1", settings=_paper_messages())
    _, read2 = message_tools(bus, "agent-2", settings=_paper_messages())
    anyio.run(lambda: ToolDef(send1).tool(to="u02", text="first"))
    anyio.run(lambda: ToolDef(send1).tool(to="u02", text="second"))
    first = anyio.run(ToolDef(read2).tool)
    assert "first" in first and "second" in first
    assert anyio.run(ToolDef(read2).tool) == first  # every message received, every time
    with pytest.raises(ToolError, match="Colleagues here: u02, u03"):
        anyio.run(lambda: ToolDef(send1).tool(to="all", text="hi everyone"))


def test_a_read_never_takes_more_than_it_can_show():
    from swarmbench.engine.messages import MAX_TEXT, SHOWN_BYTES, MessageBus, SwarmLog

    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 2}}))
    bus = MessageBus(SwarmLog(), infos)
    for _ in range(5):
        bus.send("agent-1", "u02", "∑" * MAX_TEXT)  # 3 bytes a character: cut to MAX_TEXT bytes
    assert all(len(m.text.encode()) <= MAX_TEXT for m in bus.log.messages)
    taken = bus.take_unread("agent-2")
    assert len(bus.format(taken).encode()) <= SHOWN_BYTES and len(taken) >= 1
    assert len(bus.unread["agent-2"]) == 5 - len(taken)  # the rest wait for the next read


def test_history_marks_read_only_what_it_shows_and_shows_the_rest_next():
    import anyio

    from swarmbench.engine.messages import MAX_TEXT, MessageBus, SwarmLog, message_tools

    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 2}}))
    bus = MessageBus(SwarmLog(), infos)
    bus.send("agent-1", "u02", "A" * (MAX_TEXT - 10))
    bus.send("agent-1", "u02", "B" * (MAX_TEXT - 10))
    _, read = message_tools(bus, "agent-2", settings=_paper_messages())
    first = anyio.run(ToolDef(read).tool)
    assert "AAAA" in first and "BBBB" not in first and "1 more new messages" in first
    assert [m.read_by for m in bus.log.messages] == [["agent-2"], []]  # the second is still unread
    second = anyio.run(ToolDef(read).tool)
    assert "BBBB" in second and "earlier messages not shown" in second
    assert all(m.read_by == ["agent-2"] for m in bus.log.messages)


def test_command_tools_need_antigravity_with_native_tools():
    base = {"name": "s", "prompt": "p", "swarm": {"agents": 1, "harness": "antigravity"}}
    tool = {"name": "post_intent", "description": "Post it.", "command": ["/opt/bin/post"]}
    with pytest.raises(ValueError, match="needs advanced.antigravity_native_tools"):
        Scenario.model_validate({**base, "advanced": {"command_tools": [tool]}})
    with pytest.raises(ValueError, match="needs the antigravity harness"):
        Scenario.model_validate(
            {**base, "swarm": {"agents": 1}, "advanced": {"antigravity_native_tools": True, "command_tools": [tool]}}
        )
    with pytest.raises(ValueError, match="distinct names"):
        Scenario.model_validate(
            {**base, "advanced": {"antigravity_native_tools": True, "command_tools": [{**tool, "name": "send_message"}]}}
        )
    Scenario.model_validate({**base, "advanced": {"antigravity_native_tools": True, "command_tools": [tool]}})
    # what counts is each agent's own harness, which advanced.extra.harnesses can change
    mixed = {"antigravity_native_tools": True, "command_tools": [tool], "extra": {"harnesses": ["react"]}}
    with pytest.raises(ValueError, match="needs the antigravity harness"):
        Scenario.model_validate({**base, "advanced": mixed})
    overridden = {**mixed, "extra": {"harnesses": ["antigravity"]}}
    Scenario.model_validate({**base, "swarm": {"agents": 1}, "advanced": overridden})


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


def test_a_proposed_message_runs_although_the_sdk_added_its_own_fields():
    """The SDK adds toolAction/toolSummary to every call; the message server never receives them."""
    from inspect_ai.agent import AgentState
    from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
    from inspect_ai.model._call_tools import get_tools_info

    from swarmbench.engine.geminitools import install
    from swarmbench.engine.messages import MessageBus, SwarmLog, message_tools

    install()
    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 2}}))
    tools = message_tools(MessageBus(SwarmLog(), infos), infos[0].name, via_bridge=True)
    bridge = SandboxAgentBridge(AgentState(messages=[]), None, None, None, port=0, model=None)
    bridge.register_bridged_tools("messages", {ToolDef(t).name: t for t in tools})
    declared = get_tools_info(tools)  # as the SDK declares them: the served descriptions
    proposed = {"to": "u02", "text": "hi", "toolAction": "Sending", "toolSummary": "Say hi"}
    bridge.register_tool_execution_grants([ToolCall(id="1", function="send_message", arguments=proposed)], declared)
    assert bridge.consume_tool_execution_grant("messages", "send_message", {"to": "u02", "text": "hi"})
    # only the proposed message, and only once
    assert not bridge.consume_tool_execution_grant("messages", "send_message", {"to": "u02", "text": "hi"})
    bridge.register_tool_execution_grants([ToolCall(id="2", function="send_message", arguments=proposed)], declared)
    assert not bridge.consume_tool_execution_grant("messages", "send_message", {"to": "u02", "text": "other"})



def test_sdk_fields_stay_in_a_grant_when_a_bridged_tool_takes_them():
    from inspect_ai.agent import AgentState
    from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
    from inspect_ai.model._call_tools import get_tools_info

    from swarmbench.engine.geminitools import install

    install()

    async def note(toolAction: str) -> str:
        return toolAction

    t = ToolDef(note, name="note", description="Write a note.", parameters=ToolParams(
        properties={"toolAction": ToolParam(type="string", description="what")}, required=["toolAction"]
    )).as_tool()
    bridge = SandboxAgentBridge(AgentState(messages=[]), None, None, None, port=0, model=None)
    bridge.register_bridged_tools("notes", {"note": t})
    call = ToolCall(id="1", function="note", arguments={"toolAction": "x"})
    bridge.register_tool_execution_grants([call], get_tools_info([t]))
    assert bridge.consume_tool_execution_grant("notes", "note", {"toolAction": "x"})


def test_without_previews_a_wake_note_says_what_arrived_but_not_what_it_says():
    from types import SimpleNamespace

    from swarmbench.engine.messages import MessageBus, SwarmLog
    from swarmbench.engine.wake import WakeController

    infos = agent_infos(Scenario.model_validate({"name": "s", "prompt": "p", "swarm": {"agents": 3}}))
    log = SwarmLog()
    bus = MessageBus(log, infos)
    dm = bus.send("agent-2", "u01", "the secret plan")
    post = log.add(sender="agent-3", to="all", text="public idea", channel="board", board_channel="exploring")
    wake = WakeController.__new__(WakeController)
    art = SimpleNamespace(team=SimpleNamespace(bus=bus, direct=True))
    for settings, expect, absent in [
        (_paper_messages(), ["1 new direct message(s) from u02; read them with get_messages",
                             "new posts on the board: #exploring (1)"], ["secret", "public idea"]),
        (None, ["u02 messaged you: the secret plan", "u03 posted in #exploring: public idea"], []),
    ]:
        advanced = {"direct_messages": settings.model_dump()} if settings else {}
        wake.swarm = SimpleNamespace(scenario=Scenario.model_validate({"name": "s", "prompt": "p", "advanced": advanced}))
        note = wake._format(art, [dm, post], [])
        assert all(line in note for line in expect) and not any(word in note for word in absent), note
