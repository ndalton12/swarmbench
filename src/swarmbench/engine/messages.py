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
from inspect_ai.tool import Tool, ToolDef, ToolError, ToolParam, ToolParams

from swarmbench.config import DirectMessages, MessageTool
from swarmbench.types import AgentInfo, SwarmMessage

MAX_TEXT = 8_000
MAX_SHOWN = 50
SHOWN_CHARS = 12_000
"""Messages one read returns, in characters: under Inspect's tool-output limit (16 KiB), so a
read never marks as read a message whose text was then cut from the output."""

SEND = MessageTool(name="send_message", description="Send a message to a colleague on this host.")
READ = MessageTool(name="check_messages", description="Show new messages sent to you.")


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

    def send(
        self,
        sender: str,
        to_user: str,
        text: str,
        via_bridge_of: str | None = None,
        broadcast: bool = True,
        list_users: bool = True,
    ) -> SwarmMessage:
        text = text[:MAX_TEXT]
        if to_user == "all" and broadcast:
            recipients = [a for a in self.members if a != sender]
            to = "all"
        else:
            target = self.agent_of_user(to_user)
            if target is None:
                if list_users:
                    raise ToolError(f"no such user '{to_user}'. Use list_users to see who is on this host.")
                others = sorted(info.user for name, info in self.members.items() if name != sender)
                raise ToolError(f"no such user '{to_user}'. Colleagues here: {', '.join(others)}.")
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
        """The oldest unread messages (at most MAX_SHOWN, and SHOWN_CHARS of text); the rest stay
        unread for next time."""
        ids = self.unread.get(agent, [])
        taken: list[int] = []
        chars = 0
        for i in ids[:MAX_SHOWN]:
            m = self.log.get(i)
            size = len(m.text) + 40 if m is not None else 0
            if taken and chars + size > SHOWN_CHARS:
                break
            taken.append(i)
            chars += size
        self.unread[agent] = ids[len(taken) :]
        messages = [m for m in (self.log.get(i) for i in taken) if m is not None]
        self.log.mark_read(agent, [m.id for m in messages])
        return messages

    def history(self, agent: str) -> tuple[list[SwarmMessage], int]:
        """Every direct message delivered to ``agent``, newest last: the most recent that fit in
        SHOWN_CHARS, and how many earlier ones were left out. All of them count as read."""
        received = [m for m in self.log.messages if m.channel == "direct" and agent in m.delivered_to]
        self.log.mark_read(agent, [m.id for m in received if agent not in m.read_by])
        self.unread[agent] = []
        shown: list[SwarmMessage] = []
        chars = 0
        for m in reversed(received):
            size = len(m.text) + 40
            if shown and chars + size > SHOWN_CHARS:
                break
            shown.append(m)
            chars += size
        return shown[::-1], len(received) - len(shown)

    def has_unread(self, agent: str) -> bool:
        return bool(self.unread.get(agent))

    def format(self, messages: list[SwarmMessage], header: str | None = None, more: int = 0) -> str:
        lines = [header] if header else []
        for m in messages:
            stamp = m.time.astimezone().strftime("%H:%M")
            target = " (to all)" if m.to == "all" else ""
            where = f" #{m.board_channel}" if m.channel == "board" else ""
            lines.append(f"{self.user_of(m.sender)}{target}{where} [{stamp}]: {m.text}")
        if more:
            lines.append(f"({more} more unread)")
        return "\n".join(lines)

    def digest(self, agent: str) -> str | None:
        """New messages as one short notice, or None if there are none."""
        messages = self.take_unread(agent)
        if not messages:
            return None
        return self.format(messages, header="[new messages]", more=len(self.unread.get(agent, [])))


def message_tools(
    bus: MessageBus, agent: str, via_bridge: bool = False, settings: DirectMessages | None = None
) -> list[Tool]:
    """The direct-message tools (by default send_message, check_messages and list_users), bound to
    ``agent``, named, described and behaving as ``settings`` say.

    ``via_bridge`` marks tools served to an inspect-swe agent through its own
    bridge: messages they send record ``via_bridge_of=agent``.
    """
    settings = settings or DirectMessages()
    send_spec, read_spec = settings.send or SEND, settings.read or READ

    async def send(to: str, text: str) -> str:
        bus.send(
            agent,
            to.strip(),
            text,
            via_bridge_of=agent if via_bridge else None,
            broadcast=settings.broadcast,
            list_users=settings.list_users,
        )
        return "sent"

    async def read() -> str:
        if settings.read_all:
            messages, earlier = bus.history(agent)
            if not messages:
                return "no messages"
            header = f"({earlier} earlier messages not shown)" if earlier else None
            return bus.format(messages, header=header)
        messages = bus.take_unread(agent)
        if not messages:
            return "no new messages"
        return bus.format(messages, more=len(bus.unread.get(agent, [])))

    async def list_users() -> str:
        me = bus.user_of(agent)
        names = sorted(info.user for info in bus.members.values())
        return "\n".join(f"{n} (you)" if n == me else n for n in names)

    to_text = 'Their username, or "all" to message everyone.' if settings.broadcast else "Their username."
    tools = [
        ToolDef(
            send,
            name=send_spec.name,
            description=send_spec.description,
            parameters=ToolParams(
                properties={
                    "to": ToolParam(type="string", description=to_text),
                    "text": ToolParam(type="string", description="The message."),
                },
                required=["to", "text"],
            ),
        ).as_tool(),
        ToolDef(
            read, name=read_spec.name, description=read_spec.description, parameters=ToolParams()
        ).as_tool(),
    ]
    if settings.list_users:
        tools.append(
            ToolDef(
                list_users,
                name="list_users",
                description="List the people on this host you can message.",
                parameters=ToolParams(),
            ).as_tool()
        )
    return tools
