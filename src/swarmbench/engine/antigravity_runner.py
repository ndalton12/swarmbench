"""Runs one Antigravity SDK session inside the container (copied there by antigravity.py).

Standalone: it runs under the SDK's own Python, so it imports nothing from swarmbench.
It reads a JSON request, starts the SDK agent with its own built-in tools (shell commands,
file viewing and editing, search) plus the MCP servers it is given, sends one prompt, and
prints a JSON result line. Every session of one agent uses the same conversation id
(created the first time, resumed after that), so a wake continues the same conversation.

The SDK tells the model that it is woken when a background command finishes or a timer it
set fires, and not to poll. That only happens while the engine is running, so after the
turn ends the session stays open while such work is pending, letting the engine resume
the conversation itself; it ends once nothing is left that could resume it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

# Tools left out: no network here, no user to answer questions, no image model, and
# sub-agents stay off (as for the other harnesses' own sub-agent tools, they would only
# add requests the swarm can't tell apart).
DISABLED_TOOLS = ("search_web", "read_url_content", "generate_image", "ask_question", "start_subagent")
POLL_SECONDS = 1.0
SETTLE_SECONDS = 3.0
"""After the last pending work ends, how long to wait for the engine to pick up its result."""

_engines: list[subprocess.Popen] = []  # type: ignore[type-arg]
# the engine's own status lines in a task log ("[<time>] Timer fired."), not the prompt text
_STATUS = re.compile(
    r"^\[[^\]]*\] (Timer fired\.|Timer cancelled|Cron triggered|Next scheduled fire time)", re.MULTILINE
)


def _die_with_parent() -> None:
    import ctypes

    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG


class _Popen(subprocess.Popen):  # type: ignore[type-arg]
    """The SDK's engine process ends when this runner does, even if the runner is killed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("preexec_fn", _die_with_parent)
        super().__init__(*args, **kwargs)
        _engines.append(self)


def _running_commands() -> bool:
    """Is a command the engine started still running (a backgrounded ``run_command``)?"""
    engine_pids = {p.pid for p in _engines}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/stat") as f:
                fields = f.read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if fields[0] != "Z" and int(fields[1]) in engine_pids:
            return True
    return False


def _timer_pending(log: str) -> bool:
    """Is a timer or cron job (from the engine's ``schedule`` tool) still due to fire?"""
    status = _STATUS.findall(log)
    if "Timer cancelled" in status:
        return False
    if log.startswith("Successfully scheduled one-shot timer"):
        return "Timer fired." not in status
    if log.startswith("Successfully scheduled cron job"):
        return not status or status[-1] == "Next scheduled fire time"
    return False


def _pending(request: dict[str, Any], since: float) -> bool:
    """Background work that will resume the conversation. Only this session's timers count:
    an earlier session's engine is gone, and so are its timers."""
    if _running_commands():
        return True
    tasks = Path(request["app_data_dir"], "brain", request["conversation_id"], ".system_generated", "tasks")
    for log in tasks.glob("*.log") if tasks.is_dir() else []:
        try:
            if log.stat().st_mtime >= since and _timer_pending(log.read_text(errors="replace")):
                return True
        except OSError:
            continue
    return False


async def _settle(conversation: Any, request: dict[str, Any], since: float) -> None:
    """Keep the engine running while it has background work that will resume the conversation."""
    quiet_since: float | None = None
    loop = asyncio.get_running_loop()
    while True:
        # takes whatever the engine sent, while working or not (an error raises here)
        async for _ in conversation.receive_steps():
            quiet_since = None
        if any(p.poll() is not None for p in _engines):
            raise RuntimeError("the agent engine exited")
        if _pending(request, since):
            quiet_since = None
        elif quiet_since is None:
            quiet_since = loop.time()
        elif loop.time() - quiet_since >= SETTLE_SECONDS:
            return
        await asyncio.sleep(POLL_SECONDS)


BOARD = "/usr/local/bin/board"
_PLAIN_POPEN = subprocess.Popen
"""Popen before ``main`` swaps in ``_Popen``: a board command is not an engine process."""
BOARD_DESCRIPTIONS = {
    "post_to_board": "Post a message on the shared board, in one of its channels (e.g. general).",
    "read_board": "Read the shared board: every channel, or just one.",
}


def _root_error(error: BaseException) -> str:
    """The innermost error behind exception groups (what an MCP client failure actually was)."""
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return f"{type(error).__name__}: {error}"


def _board(*args: str) -> str:
    with _PLAIN_POPEN(
        [BOARD, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as p:
        try:
            out, _ = p.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
    return out.strip() or "(no output)"


def native_tools(request: dict[str, Any]) -> list[Any]:
    """The board and/or direct messages (``request["native_tools"]``) as the SDK's own tools.

    Messages go to the same MCP server the wrapper would use. The bridge runs a message tool only
    for a call the model proposed, and it recognises the tool by the description it served for it,
    so each message tool carries exactly that description (``message_descriptions``); the SDK
    describes a tool to the model by its ``__doc__``. The board is the host ``board`` command,
    run as this agent."""
    groups = request.get("native_tools") or []
    server = next((s for s in request["mcp_servers"] if s["name"] == request.get("messages_server")), None)
    descriptions = request.get("message_descriptions") or {}

    async def call(name: str, arguments: dict[str, Any]) -> str:
        if server is None:
            return "Direct messages are not available here."
        from mcp import ClientSession
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        try:
            async with (
                create_mcp_http_client(headers=server.get("headers")) as http,
                streamable_http_client(server["url"], http_client=http) as streams,
            ):
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
        except Exception as e:
            return f"{name} failed: {_root_error(e)}"
        return (
            "\n".join(getattr(c, "text", "") for c in getattr(result, "content", []) or []) or "(no output)"
        )

    async def send_message(to: str, text: str) -> str:
        return await call("send_message", {"to": to, "text": text})

    async def check_messages() -> str:
        return await call("check_messages", {})

    async def list_users() -> str:
        return await call("list_users", {})

    def post_to_board(channel: str, text: str) -> str:
        return _board("post", f"--message={text}", "--", channel)

    def read_board(channel: str = "") -> str:
        return _board("read", *(["--", channel] if channel else []))

    tools: list[Any] = []
    if "messages" in groups:
        for fn in (send_message, check_messages, list_users):
            fn.__doc__ = descriptions.get(fn.__name__, "")
            tools.append(fn)
    if "board" in groups:
        for fn in (post_to_board, read_board):
            fn.__doc__ = BOARD_DESCRIPTIONS[fn.__name__]
            tools.append(fn)
    return tools


def build_config(request: dict[str, Any]) -> Any:
    from google.antigravity import LocalAgentConfig, types
    from google.antigravity.hooks import policy

    options = (
        types.GeminiModelOptions(thinking_level=request["thinking_level"])
        if request.get("thinking_level")
        else None
    )
    model = types.ModelTarget(
        name=request["model"],
        # one target for both kinds, so no default model (with its own endpoint) is added
        types=[types.ModelType.TEXT, types.ModelType.IMAGE],
        endpoint=types.GeminiAPIEndpoint(
            base_url=request["base_url"], api_key=request["api_key"], options=options
        ),
    )
    native = native_tools(request) if request.get("native_tools") else []
    servers = [
        types.McpStreamableHttpServer(name=s["name"], url=s["url"], headers=s.get("headers"))
        for s in request["mcp_servers"]
        # with its own tools for messages, the agent doesn't also get them through the MCP wrapper
        if not (
            "messages" in (request.get("native_tools") or []) and s["name"] == request.get("messages_server")
        )
    ]
    config = LocalAgentConfig(
        models=[model],
        system_instructions=request["system_instructions"] or None,
        capabilities=types.CapabilitiesConfig(
            disabled_tools=[types.BuiltinTools(t) for t in DISABLED_TOOLS],
            enable_subagents=False,
        ),
        mcp_servers=servers,
        tools=native or None,
        policies=[policy.allow_all()],
        workspaces=[request["cwd"]],
        app_data_dir=request["app_data_dir"],
        save_dir=request["save_dir"],
        conversation_id=request["conversation_id"],
        session_continuation_mode=types.SessionContinuationMode.CREATE_OR_RESUME,
    )
    # The workspace names the project; it shouldn't also fence the file tools in (the
    # shell can reach everything anyway, and the other harnesses' file tools aren't fenced).
    config.__dict__["policies"] = [p for p in config.policies if getattr(p, "name", "") != "workspace_only"]
    return config


async def run(request: dict[str, Any]) -> None:
    from google.antigravity import Agent

    started = time.time()
    async with Agent(build_config(request)) as agent:
        response = await agent.chat(request["prompt"])
        text = await response.text()
        await _settle(agent.conversation, request, started - 1)
        print(json.dumps({"conversation_id": agent.conversation_id, "final_text": text}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    subprocess.Popen = _Popen  # type: ignore[misc]
    os.umask(0o077)  # the agent's files are private unless it shares them
    request = json.loads(Path(args.config).read_text())
    asyncio.run(run(request))


if __name__ == "__main__":
    main()
