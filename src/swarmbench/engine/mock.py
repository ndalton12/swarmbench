"""Scripted mock model for dry runs and tests (no API calls).

One ``mockllm/model`` instance serves every agent. It works out which agent is
calling from ``current_agent()`` (the bridge's service task inherits it), and
which step of that agent's script comes next from how many tool-using replies
are already in the conversation. Steps are written once and mapped onto each
harness's own tool names (``bash`` for react, ``Bash`` for Claude Code, Codex's
shell tool, Antigravity's ``run_command``, and the bridged message tools).
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from swarmbench.types import AgentInfo

from .bridgefilter import identity_text
from .context import current_agent

MCP_SERVER = "messages"
"""Name of the bridged message tools' MCP server (harness.BRIDGED_SERVER)."""

Step = tuple[Any, ...]
"""("shell", command) | ("send", to_user, text) | ("check",) | ("python", code)
| ("final", text). A callable step is called with the AgentInfo and returns one of these."""


def default_script(info: AgentInfo, others: list[AgentInfo], board: bool, direct: bool) -> list[Step]:
    """A short script that touches every path: shell, a direct message, a board post, reads.

    Each agent sends its direct message before posting to the board, then waits until
    every agent has posted (or 60 s), so all messages exist before anyone checks.
    """
    peer = others[0].user if others else info.user
    steps: list[Step] = [("shell", "id; hostname; ls -la /workspace | head -20")]
    if direct:
        steps.append(("send", peer, f"hi {peer}, {info.user} here. I'll take the first part."))
    if board:
        steps.append(
            ("shell", f"board post general -m {shlex.quote(f'{info.user} here, starting on the task.')}")
        )
        users = [info.user] + [o.user for o in others]
        wait = " && ".join(f"ls /board/general | grep -q -- '-{u}.md$'" for u in users)
        steps.append(("shell", f"for i in $(seq 60); do {wait} && break; sleep 1; done; board read --new"))
    else:
        steps.append(("shell", "sleep 15"))
    if direct:
        steps.append(("check",))
    steps.append(("final", "Done for now."))
    return steps


def _tool(tools: list[ToolInfo], *names: str) -> ToolInfo | None:
    by_name = {t.name: t for t in tools}
    for n in names:
        if n in by_name:
            return by_name[n]
    for t in tools:  # MCP tools are prefixed, e.g. mcp__messages__send_message
        for n in names:
            if t.name.endswith(f"__{n}") or t.name.endswith(f".{n}"):
                return t
    return None


def _shell_call(tools: list[ToolInfo], command: str) -> tuple[str, dict[str, Any]] | None:
    t = _tool(tools, "bash", "Bash", "exec_command", "shell", "local_shell", "run_command")
    if t is None:
        return None
    props = t.parameters.properties
    if "CommandLine" in props:  # Antigravity
        return t.name, {
            "CommandLine": command,
            "Cwd": "/workspace",
            "WaitMsBeforeAsync": 10000,
            "toolSummary": "Command execution",
            "toolAction": "Running command",
        }
    if "cmd" in props:
        return t.name, {"cmd": command}
    if "command" in props:
        if props["command"].type == "array":
            return t.name, {"command": ["bash", "-lc", command]}
        args: dict[str, Any] = {"command": command}
        if "description" in props:
            args["description"] = "run a command"
        return t.name, args
    return t.name, {next(iter(props)): command}


def _message_call(tools: list[ToolInfo], name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """A call to a bridged tool: direct, or through Antigravity's ``call_mcp_tool``."""
    t = _tool(tools, name)
    if t is not None:
        return t.name, args
    if _tool(tools, "call_mcp_tool") is not None:
        return "call_mcp_tool", {
            "ServerName": MCP_SERVER,
            "ToolName": name,
            "Arguments": args,
            "toolSummary": "Message tool",
            "toolAction": "Calling message tool",
        }
    return None


WAKE_PREFIX = "[activity on this host]"


def _unwrapped(text: str) -> str:
    """A user message's text without the wrapper Antigravity puts around each request."""
    return text.lstrip().removeprefix("<USER_REQUEST>").lstrip()


def _progress(messages: list[ChatMessage]) -> int:
    """How far through its script an agent is: its tool calls, plus wake notes resuming it.

    A script step that ends the turn (``final``) produces no tool call, so after a wake the
    conversation's tool-call count hasn't advanced; the wake note (a user message) counts
    instead, so the next session continues where the script left off.
    """
    tool_calls = sum(1 for m in messages if isinstance(m, ChatMessageAssistant) and m.tool_calls)
    wakes = sum(1 for m in messages if m.role == "user" and _unwrapped(m.text).startswith(WAKE_PREFIX))
    return tool_calls + wakes


class MockSwarmModel:
    """Callable for mockllm's ``custom_outputs``."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[Step]] = {}
        self.infos: dict[str, AgentInfo] = {}
        self.calls: list[dict[str, Any]] = []
        """Every call: agent, number of messages, tool names (for tests)."""
        self.message_names: dict[str, str] = {}
        """The scenario's names for send_message / check_messages, when it renames them."""

    def set_script(self, info: AgentInfo, steps: list[Step]) -> None:
        self.infos[info.name] = info
        self.scripts.setdefault(info.name, steps)

    def __call__(
        self, input: list[ChatMessage], tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> ModelOutput:
        agent = current_agent()
        conv = [m for m in input if not isinstance(m, ChatMessageSystem)]
        self.calls.append({"agent": agent, "messages": len(conv), "tools": [t.name for t in tools]})
        script = self.scripts.get(agent or "")
        info = self.infos.get(agent or "")
        # side calls (no tools: titles, summaries, quota checks), sub-agents, requests sent
        # through this agent's bridge by someone else, and unknown callers get plain text
        own = info is not None and re.search(rf"\bis {re.escape(info.user)}\b", identity_text(input))
        if not tools or script is None or not own:
            self.calls[-1]["scripted"] = False
            return ModelOutput.from_content(model="mockllm/model", content="OK")
        index = _progress(conv)
        if index >= len(script):
            return ModelOutput.from_content(model="mockllm/model", content="Done.")
        step = script[index]
        if callable(step):
            step = step(self.infos[agent])  # type: ignore[index]
        return self._output(step, tools, index)

    def _output(self, step: Step, tools: list[ToolInfo], index: int) -> ModelOutput:
        kind = step[0]
        call: tuple[str, dict[str, Any]] | None = None
        if kind == "shell":
            call = _shell_call(tools, step[1])
        elif kind == "python":
            t = _tool(tools, "python")
            call = (
                (t.name, {"code": step[1]}) if t else _shell_call(tools, f"python3 -c {shlex.quote(step[1])}")
            )
        elif kind == "send":
            send = self.message_names.get("send_message", "send_message")
            call = _message_call(tools, send, {"to": step[1], "text": step[2]})
        elif kind == "check":
            call = _message_call(tools, self.message_names.get("check_messages", "check_messages"), {})
        elif kind == "tool":
            t = _tool(tools, step[1])
            call = (t.name, step[2]) if t else None
        elif kind == "final":
            return ModelOutput.from_content(model="mockllm/model", content=step[1])
        if call is None:
            # the harness lacks this tool: skip the step with a harmless shell call
            call = _shell_call(tools, "true") or ("", {})
            if not call[0]:
                return ModelOutput.from_content(model="mockllm/model", content="Done.")
        name, args = call
        return ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name=name,
            tool_arguments=args,
            tool_call_id=f"call_{index}_{name}"[:60],
        )


def mock_model(dispatcher: MockSwarmModel) -> Model:
    return get_model("mockllm/model", custom_outputs=dispatcher, memoize=False)
