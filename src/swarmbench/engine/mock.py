"""Scripted mock model for dry runs and tests (no API calls).

One ``mockllm/model`` instance serves every agent. It works out which agent is
calling from ``current_agent()`` (the bridge's service task inherits it), and
which step of that agent's script comes next from how many tool-using replies
are already in the conversation. Steps are written once and mapped onto each
harness's own tool names (``bash`` for react, ``Bash`` for Claude Code, Codex's
shell tool, and the bridged message tools).
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
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

Step = tuple[Any, ...]
"""("shell", command) | ("send", to_user, text) | ("check",) | ("python", code)
| ("final", text). A callable step is called with the AgentInfo and returns one of these."""


def default_script(info: AgentInfo, others: list[AgentInfo], board: bool, direct: bool) -> list[Step]:
    peer = others[0].user if others else info.user
    steps: list[Step] = [("shell", "id; hostname; ls -la /workspace | head -20")]
    if board:
        steps.append(
            ("shell", f"board post general -m {shlex.quote(f'{info.user} here, starting on the task.')}")
        )
    if direct:
        steps.append(("send", peer, f"hi {peer}, {info.user} here. I'll take the first part."))
        steps.append(("check",))
    if board:
        steps.append(("shell", "sleep 3; board read --new"))
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
    t = _tool(tools, "bash", "Bash", "exec_command", "shell", "local_shell")
    if t is None:
        return None
    props = t.parameters.properties
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


def _progress(messages: list[ChatMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, ChatMessageAssistant) and m.tool_calls)


class MockSwarmModel:
    """Callable for mockllm's ``custom_outputs``."""

    def __init__(self) -> None:
        self.scripts: dict[str, list[Step]] = {}
        self.infos: dict[str, AgentInfo] = {}
        self.calls: list[dict[str, Any]] = []
        """Every call: agent, number of messages, tool names (for tests)."""

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
            t = _tool(tools, "send_message")
            call = (t.name, {"to": step[1], "text": step[2]}) if t else None
        elif kind == "check":
            t = _tool(tools, "check_messages")
            call = (t.name, {}) if t else None
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


def dump(obj: Any) -> str:
    return json.dumps(obj, default=str)


__all__ = ["MockSwarmModel", "default_script", "mock_model", "Step", "Callable"]
