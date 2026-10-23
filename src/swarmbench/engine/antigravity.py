"""The Antigravity harness: Google's Antigravity SDK agent, running as one agent's Linux user.

inspect-swe has an Antigravity agent, but it is built for single-agent evals and doesn't
fit a swarm: it strips the SDK's own tools (shell, file view and edit, search) so the agent
has only MCP tools; it keeps the conversation to resume in one sample-wide store slot, so
agents sharing a sample would resume each other's conversations; and it writes its files
as root, which can't write into an agent's private home in our containers. This module
follows its structure (the model bridge, bridged MCP tools, one runner process per
session) but runs the SDK with its own built-in tools, one conversation per agent, and
every file written as the agent.

The SDK is baked into the base image at ``SDK_PYTHON``'s virtualenv (containers are offline).
Requests reach the bridge in Gemini's wire format (the SDK's native ``generateContent``).
"""

from __future__ import annotations

import ast
import json
import shlex
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import anyio
from inspect_ai.agent import Agent, AgentState, BridgedToolsSpec, agent, agent_with, sandbox_agent_bridge
from inspect_ai.model import GenerateFilter, Model
from inspect_ai.tool._mcp._config import MCPServerConfigHTTP
from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util import store
from inspect_ai.util._sandbox import ExecRemoteAwaitableOptions

SDK_PYTHON = "/usr/local/lib/antigravity/bin/python"
"""Python of the SDK's virtualenv in the base image (see docker/Dockerfile)."""
ENGINE = "localharness"
"""The SDK's agent engine (a compiled program it starts for each session)."""
PORT_KEY = "antigravity_bridge_port"
DATA_DIR = ".gemini/antigravity"
"""The SDK's own data folder (its default), relative to the agent's home."""
STATE_DIR = ".gemini/antigravity-sdk"
"""Runner, request and saved sessions, relative to the agent's home."""
RUNNER = Path(__file__).with_name("antigravity_runner.py")
DUMMY_API_KEY = "unused"
"""All requests go to the local bridge, which ignores the key; the SDK wants one set."""
EFFORT_THINKING = {"low": "low", "medium": "medium", "high": "high", "xhigh": "extra_high", "max": "extra_high"}
MCP_READY_TIMEOUT = 120.0
CLEANUP_SECONDS = 20


def _messages_server() -> str:
    from .harness import BRIDGED_SERVER  # here, not at import: harness imports this module

    return BRIDGED_SERVER


def _served_descriptions(bridged_tools: Sequence[BridgedToolsSpec] | None, server: str) -> dict[str, str]:
    """Each bridged tool's description as the bridge serves it (and matches proposed calls by)."""
    from inspect_ai.model._call_tools import get_tools_info

    specs = [spec for spec in bridged_tools or [] if spec.name == server]
    return {info.name: info.description for spec in specs for info in get_tools_info(list(spec.tools))}


def runner_source() -> str:
    """The runner as the agent sees it in its home: the code without our docstrings and comments
    (they describe the test setup)."""
    tree = ast.parse(RUNNER.read_text())
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            kept = [
                n
                for n in body
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))
            ]
            node.body = kept or [ast.Pass()]  # type: ignore[attr-defined]
    return '"""Run an agent session from a JSON request."""\n\n' + ast.unparse(tree) + "\n"


@agent
def antigravity(
    name: str = "Antigravity",
    *,
    system_prompt: str | None = None,
    bridged_tools: Sequence[BridgedToolsSpec] | None = None,
    model: Model | None = None,
    endpoint_model: str = "gemini",
    effort: str | None = None,
    filter: GenerateFilter | None = None,
    home: str,
    cwd: str,
    env: dict[str, str] | None = None,
    user: str,
    sandbox: str | None = None,
    native_tools: Sequence[str] = (),
) -> Agent:
    """Antigravity SDK agent.

    Args:
        name: Agent name.
        system_prompt: Appended to the SDK's own system instructions.
        bridged_tools: Host-side Inspect tools offered to the agent over MCP.
        model: The model every request goes to (None: the task's model, as in dry runs).
            Its own config applies (e.g. reasoning effort); the bridge drops the SDK's.
        endpoint_model: Model name the SDK presents to the bridge.
        effort: Thinking level the SDK asks for (low/medium/high/xhigh/max).
        filter: Generate filter for every request through this agent's bridge.
        home: The agent's home directory (the SDK's state lives there).
        cwd: Working directory, also the SDK's workspace.
        env: Extra environment for the runner and everything it starts.
        user: Linux user the SDK runs as.
        sandbox: Sandbox (container) name.
        native_tools: What to offer as the SDK's own tools (run.py's native_tools): "board"
            and/or "messages" (direct messages, otherwise behind the SDK's generic MCP wrapper).
    """
    # Same id for every session of this agent: the first creates it, later ones resume it.
    conversation_id = str(uuid.uuid4())

    async def execute(state: AgentState) -> AgentState:
        from inspect_swe._util.mcp_ready import wait_for_mcp_endpoints
        from inspect_swe._util.messages import build_user_prompt

        port = store().get(PORT_KEY, 3000) + 1
        store().set(PORT_KEY, port)

        async with sandbox_agent_bridge(
            state,
            # any other name the SDK might send goes to the same model (without its config)
            model=f"inspect/{model}" if model is not None else None,
            model_aliases={endpoint_model: model} if model is not None else None,
            filter=filter,
            sandbox=sandbox,
            port=port,
            bridged_tools=bridged_tools,
        ) as bridge:
            sbox = sandbox_env(sandbox)

            async def run_as_user(script: str, input: str | None = None) -> None:
                result = await sbox.exec(["sh", "-c", script], user=user, input=input, timeout=120)
                if not result.success:
                    raise RuntimeError(f"Antigravity setup failed: {result.stderr.strip()[-500:]}")

            check = await sbox.exec(
                [SDK_PYTHON, "-c", "import google.antigravity"], user=user, env={"PYTHONNOUSERSITE": "1"}
            )
            if not check.success:
                raise RuntimeError(
                    f"the Antigravity SDK is missing from the image ({SDK_PYTHON}); rebuild the base "
                    f"image: {check.stderr.strip()[-300:]}"
                )

            configs = [c for c in bridge.mcp_server_configs if isinstance(c, MCPServerConfigHTTP)]
            if configs:
                await wait_for_mcp_endpoints(
                    configs, bridge, sandbox=sandbox, timeout=MCP_READY_TIMEOUT, required=True
                )

            # only the new user messages: a resumed conversation already has the rest. The
            # state's system message (from an earlier session) is the SDK's own full prompt
            # as the bridge saw it, so it isn't passed back in.
            prompt, _ = build_user_prompt(state.messages)

            state_dir = f"{home}/{STATE_DIR}"
            runner, request_file = f"{state_dir}/run.py", f"{state_dir}/request.json"
            request: dict[str, Any] = {
                "prompt": prompt,
                "system_instructions": system_prompt or "",
                "model": endpoint_model,
                "base_url": f"http://127.0.0.1:{bridge.port}",
                "api_key": DUMMY_API_KEY,
                "thinking_level": EFFORT_THINKING.get(effort or ""),
                "mcp_servers": [{"name": c.name, "url": c.url, "headers": c.headers} for c in configs],
                "cwd": cwd,
                "app_data_dir": f"{home}/{DATA_DIR}",
                "save_dir": f"{state_dir}/sessions",
                "conversation_id": conversation_id,
                "native_tools": list(native_tools),
                "messages_server": _messages_server(),
                "message_descriptions": _served_descriptions(bridged_tools, _messages_server()),
            }
            async def stop_leftovers() -> None:
                # a runner (and its engine) left from an interrupted session, e.g. one cancelled
                # while starting, before Inspect knew its process; the agent's own jobs stay
                with anyio.CancelScope(shield=True), anyio.move_on_after(CLEANUP_SECONDS):
                    for match in (["-f", f"^{SDK_PYTHON} {runner} "], ["-x", ENGINE]):
                        try:
                            await sbox.exec(
                                ["pkill", "-KILL", "-u", user, *match],
                                user=user,
                                timeout=CLEANUP_SECONDS,
                                timeout_retry=False,
                                concurrency=False,
                            )
                        except Exception:
                            pass

            await stop_leftovers()
            # written as the agent: root can't write into an agent's private folders here
            await run_as_user(
                f"umask 077 && mkdir -p {shlex.quote(home + '/' + DATA_DIR)} {shlex.quote(state_dir)}"
            )
            await run_as_user(f"umask 077 && cat > {shlex.quote(runner)}", runner_source())
            await run_as_user(f"umask 077 && cat > {shlex.quote(request_file)}", json.dumps(request))

            try:
                result = await sbox.exec_remote(
                    cmd=[SDK_PYTHON, runner, "--config", request_file],
                    options=ExecRemoteAwaitableOptions(
                        concurrency=False,
                        cwd=cwd,
                        env={
                            **(env or {}),
                            "HOME": home,
                            "PYTHONNOUSERSITE": "1",
                            "NO_PROXY": "127.0.0.1,localhost",
                            "no_proxy": "127.0.0.1,localhost",
                        },
                        user=user,
                    ),
                    stream=False,
                )
            finally:
                # the engine dies with the runner (see the runner); this also catches a runner
                # Inspect didn't get to stop
                await stop_leftovers()
            if not result.success:
                detail = result.stderr.strip()[-2000:] or result.stdout.strip()[-2000:]
                raise RuntimeError(f"Antigravity SDK exited {result.returncode}: {detail}")

        return bridge.state

    return agent_with(execute, name=name, description="Antigravity SDK agent.")
