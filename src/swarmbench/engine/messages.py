"""Message history and direct messaging between agents.

``SwarmLog`` holds every message of a sample (direct messages and board posts)
and records them as ``swarm.message`` / ``swarm.read`` events. ``MessageBus`` is
one team's direct-message service, and ``message_tools`` gives each agent its
own tool instances with its identity bound in.

Agents only ever see Linux user names (``u03``); internal agent names
(``agent-3``) appear only in the log.
"""

from __future__ import annotations

from collections.abc import Callable

from inspect_ai.log import transcript
from inspect_ai.tool import Tool, ToolError, tool

from swarmbench.types import AgentInfo, SwarmMessage

MAX_TEXT = 8_000
MAX_SHOWN = 50


class SwarmLog:
    """All messages of one sample, in order, with ids unique across teams."""

    def __init__(self) -> None:
        self.messages: list[SwarmMessage] = []
        self._by_id: dict[int, SwarmMessage] = {}
        self.listeners: list[Callable[[SwarmMessage], None]] = []

    def add(self, **fields) -> SwarmMessage:  # type: ignore[no-untyped-def]
        message = SwarmMessage(id=len(self.messages) + 1, **fields)
        self.messages.append(message)
        self._by_id[message.id] = message
        transcript().info(message.model_dump(mode="json"), source="swarm.message")
        for listener in self.listeners:
            listener(message)
        return message

    def get(self, message_id: int) -> SwarmMessage | None:
        return self._by_id.get(message_id)

    def mark_read(self, agent: str, ids: list[int]) -> None:
        if not ids:
            return
        for i in ids:
            m = self._by_id.get(i)
            if m is not None and agent not in m.read_by:
                m.read_by.append(agent)
        transcript().info({"agent": agent, "ids": ids}, source="swarm.read")


class MessageBus:
    """Direct messages within one team (or across teams after an encounter)."""

    def __init__(self, log: SwarmLog, members: list[AgentInfo]) -> None:
        self.log = log
        self.members: dict[str, AgentInfo] = {a.name: a for a in members}
        self.unread: dict[str, list[int]] = {a.name: [] for a in members}
        self.stopped: set[str] = set()

    def user_of(self, agent: str) -> str:
        info = self.members.get(agent)
        return info.user if info else agent

    def agent_of_user(self, user: str) -> str | None:
        for info in self.members.values():
            if info.user == user:
                return info.name
        return None

    def add_members(self, members: list[AgentInfo]) -> None:
        for a in members:
            self.members.setdefault(a.name, a)
            self.unread.setdefault(a.name, [])

    def send(self, sender: str, to_user: str, text: str, via_bridge_of: str | None = None) -> SwarmMessage:
        text = text[:MAX_TEXT]
        if to_user == "all":
            recipients = [a for a in self.members if a != sender]
            to = "all"
        else:
            target = self.agent_of_user(to_user)
            if target is None:
                raise ToolError(f"no such user '{to_user}'. Use list_users to see who is on this host.")
            recipients = [target]
            to = target
        message = self.log.add(
            sender=sender,
            to=to,
            text=text,
            channel="direct",
            via_bridge_of=via_bridge_of,
            delivered_to=recipients,
        )
        for r in recipients:
            self.unread[r].append(message.id)
        return message

    def take_unread(self, agent: str) -> list[SwarmMessage]:
        ids = self.unread.get(agent, [])
        self.unread[agent] = []
        messages = [m for m in (self.log.get(i) for i in ids) if m is not None]
        self.log.mark_read(agent, [m.id for m in messages])
        return messages

    def has_unread(self, agent: str) -> bool:
        return bool(self.unread.get(agent))

    def format(self, messages: list[SwarmMessage], header: str | None = None) -> str:
        lines = [header] if header else []
        shown = messages[-MAX_SHOWN:]
        if len(messages) > len(shown):
            lines.append(f"({len(messages) - len(shown)} earlier messages not shown)")
        for m in shown:
            stamp = m.time.astimezone().strftime("%H:%M")
            target = " (to all)" if m.to == "all" else ""
            lines.append(f"{self.user_of(m.sender)}{target} [{stamp}]: {m.text}")
        return "\n".join(lines)

    def digest(self, agent: str) -> str | None:
        """New messages as one short notice, or None if there are none."""
        messages = self.take_unread(agent)
        if not messages:
            return None
        return self.format(messages, header="[new messages]")


def message_tools(bus: MessageBus, agent: str, via_bridge: bool = False) -> list[Tool]:
    """send_message, check_messages and list_users, bound to ``agent``.

    ``via_bridge`` marks tools served to an inspect-swe agent through its own
    bridge: messages they send record ``via_bridge_of=agent``.
    """

    @tool(name="send_message")
    def send_message() -> Tool:
        async def execute(to: str, text: str) -> str:
            """Send a message to a colleague on this host.

            Args:
              to: Their username, or "all" to message everyone.
              text: The message.
            """
            bus.send(agent, to.strip(), text, via_bridge_of=agent if via_bridge else None)
            return "sent"

        return execute

    @tool(name="check_messages")
    def check_messages() -> Tool:
        async def execute() -> str:
            """Show new messages sent to you."""
            messages = bus.take_unread(agent)
            if not messages:
                return "no new messages"
            return bus.format(messages)

        return execute

    @tool(name="list_users")
    def list_users() -> Tool:
        async def execute() -> str:
            """List the people on this host you can message."""
            me = bus.user_of(agent)
            names = sorted(info.user for info in bus.members.values())
            return "\n".join(f"{n} (you)" if n == me else n for n in names)

        return execute

    return [send_message(), check_messages(), list_users()]
