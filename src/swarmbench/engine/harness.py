"""Building each agent: react, Claude Code or Codex CLI, running as its own Linux user."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from inspect_ai.agent import Agent, AgentPrompt, AgentState, BridgedToolsSpec, react
from inspect_ai.model import ChatMessageUser, CompactionAuto, GenerateConfig, Model, get_model
from inspect_ai.tool import Tool, ToolDef, bash, python, text_editor
from inspect_ai.util._sandbox.context import sandbox_default_context_var

from swarmbench.config import ResolvedTeam
from swarmbench.types import AgentInfo

from .bridgefilter import BridgeFilter
from .layout import WORKSPACE
from .messages import MessageBus, message_tools
from .text import render_prompt

TOOL_TIMEOUT = 600
BRIDGED_SERVER = "messages"
DISALLOWED_CLAUDE_TOOLS = ["WebSearch", "WebFetch"]
CODEX_EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}

REACT_SYSTEM = (
    "Your account on the shared Linux server {host} is {user}. You have a shell on it through the "
    "tools provided. Shared work lives in /workspace."
)


def in_sandbox(tool: Tool, sandbox: str) -> Tool:
    """Run a tool that has no ``sandbox`` argument (text_editor) against a named sandbox."""
    original = ToolDef(tool)
    inner = original.tool

    async def execute(**kwargs: Any) -> Any:
        token = sandbox_default_context_var.set(sandbox)
        try:
            return await inner(**kwargs)
        finally:
            sandbox_default_context_var.reset(token)

    return ToolDef(
        execute,
        name=original.name,
        description=original.description,
        parameters=original.parameters,
        viewer=original.viewer,
        parallel=original.parallel,
    ).as_tool()


def react_tools(info: AgentInfo, default_sandbox: str) -> list[Tool]:
    editor = text_editor(timeout=180, user=info.user)
    if info.sandbox != default_sandbox:
        editor = in_sandbox(editor, info.sandbox)
    return [
        bash(timeout=TOOL_TIMEOUT, user=info.user, sandbox=info.sandbox),
        python(timeout=TOOL_TIMEOUT, user=info.user, sandbox=info.sandbox),
        editor,
    ]


def react_continue(
    agent: str, bus: MessageBus | None, notice: bool, should_stop: Callable[[], bool]
) -> Callable[[AgentState], Awaitable[bool | str | AgentState]]:
    """After each turn: stop if asked, deliver a notice digest, end when the model stops using tools."""

    async def on_continue(state: AgentState) -> bool | str | AgentState:
        if should_stop():
            return False
        digest = bus.digest(agent) if (notice and bus is not None) else None
        if state.output.message.tool_calls:
            if digest:
                state.messages.append(ChatMessageUser(content=digest))
                return state
            return True
        return digest if digest else False

    return on_continue


def model_for(team: ResolvedTeam, effort_ok: bool, dry_model: Model | None) -> Model | None:
    if dry_model is not None:
        return dry_model
    config = GenerateConfig(reasoning_effort=team.effort) if (team.effort and effort_ok) else GenerateConfig()
    return get_model(team.model, config=config)


def build_agent(
    info: AgentInfo,
    team: ResolvedTeam,
    *,
    hostname: str,
    default_sandbox: str,
    bus: MessageBus | None,
    direct: bool,
    notice: bool,
    should_stop: Callable[[], bool],
    bridge_filter: BridgeFilter | None,
    compaction: bool,
    dry_model: Model | None,
) -> Agent:
    tools = message_tools(bus, info.name) if (direct and bus is not None) else []

    if info.harness == "react":
        return react(
            name=info.name,
            prompt=AgentPrompt(
                instructions=render_prompt(REACT_SYSTEM, info.user, hostname, []),
                handoff_prompt=None,
                assistant_prompt=None,
                submit_prompt=None,
            ),
            tools=react_tools(info, default_sandbox) + tools,
            model=model_for(team, True, dry_model),
            submit=False,
            on_continue=react_continue(info.name, bus, notice, should_stop),
            compaction=CompactionAuto() if compaction else None,
        )

    bridged = (
        [BridgedToolsSpec(name=BRIDGED_SERVER, tools=message_tools(bus, info.name, via_bridge=True))]
        if (direct and bus is not None)
        else None
    )
    model_name = None if dry_model is not None else team.model

    if info.harness == "claude_code":
        from inspect_swe import claude_code

        return claude_code(
            name=info.name,
            bridged_tools=bridged,
            disallowed_tools=DISALLOWED_CLAUDE_TOOLS,
            model=model_name,
            effort=team.effort,
            filter=bridge_filter,
            cwd=WORKSPACE,
            env={"CLAUDE_CONFIG_DIR": f"{info.home}/.claude", "HOME": info.home},
            user=info.user,
            sandbox=info.sandbox,
            version="sandbox",
        )

    if info.harness == "codex_cli":
        from inspect_swe import codex_cli

        overrides = {"model_reasoning_effort": CODEX_EFFORT[team.effort]} if team.effort else None
        return codex_cli(
            name=info.name,
            bridged_tools=bridged,
            web_search="disabled",
            model=model_name,
            # forward Codex's own request settings (including reasoning effort) to the model
            transparent_proxy=team.effort is not None,
            config_overrides=overrides,
            filter=bridge_filter,
            home_dir=f"{info.home}/.codex",
            cwd=WORKSPACE,
            env={"HOME": info.home},
            user=info.user,
            sandbox=info.sandbox,
            version="sandbox",
        )

    raise ValueError(f"unknown harness {info.harness}")
