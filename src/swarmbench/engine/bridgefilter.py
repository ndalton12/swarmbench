"""Generate filter for one inspect-swe agent's bridge.

It does three jobs on every model call that goes through the agent's bridge:

- **budget**: Inspect's ``token_limit`` can't be used for inspect-swe agents (a
  limit hit inside the bridge cancels the whole sample), so the agent's usage is
  metered by an unlimited ``token_limit(None)`` opened around the agent, and once
  it reaches the budget the filter answers with a final empty reply instead of
  calling the model, which ends the agent's session;
- **attribution**: it checks that each call continues one of this agent's own
  conversations. A call that doesn't suggests someone else is using this bridge,
  and is recorded as ``swarm.foreign_turn``;
- **notices**: with ``notice`` delivery, new direct messages are added to the
  conversation as one short user message, and re-inserted at the same place on
  later calls (the agent's CLI doesn't know about them, so it never resends them).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from inspect_ai.log import transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    GenerateInput,
    Model,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.tool import ToolChoice, ToolInfo

from .messages import MessageBus

STOP_TEXT = ""
"""Reply sent once an agent's budget is used up. Empty, so the session just ends
(a custom 'budget exhausted' message would read like a test harness)."""

STOPPED_MARK = "swarmbench_stopped"


def _fingerprint(message: ChatMessage) -> str:
    data: dict[str, Any] = {"role": message.role, "text": message.text[:2000]}
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        data["calls"] = [
            (c.function, json.dumps(c.arguments, sort_keys=True, default=str)[:500])
            for c in message.tool_calls
        ]
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def _conversation(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [m for m in messages if not isinstance(m, ChatMessageSystem)]


def usage_of(limit: Any) -> ModelUsage:
    """Usage recorded by a ``token_limit`` node (input and output, where available)."""
    usage = getattr(limit, "_usage", None)
    if isinstance(usage, ModelUsage):
        return usage
    return ModelUsage(total_tokens=int(getattr(limit, "usage", 0) or 0))


@dataclass
class BridgeFilter:
    agent: str
    prompt: str
    """The first user message this agent was given."""
    budget: int
    meter: Any
    """The agent's ``token_limit(None)`` node."""
    bus: MessageBus | None = None
    notice: bool = False
    on_exhausted: Callable[[], None] | None = None
    should_stop: Callable[[], bool] | None = None

    exhausted: bool = False
    conversations: list[list[str]] = field(default_factory=list)
    main: list[str] | None = None
    digests: list[tuple[int, str]] = field(default_factory=list)
    """(position in the main conversation, text) of each notice already delivered."""
    tool_args: set[str] = field(default_factory=set)
    foreign_calls: int = 0

    def used(self) -> int:
        return int(usage_of(self.meter).total_tokens)

    def stop_output(self, model: Model | str) -> ModelOutput:
        output = ModelOutput.from_content(model=str(model), content=STOP_TEXT, stop_reason="stop")
        output.message.metadata = {STOPPED_MARK: "budget" if self.exhausted else "stopped"}
        return output

    async def __call__(
        self,
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput | None:
        if self.should_stop is not None and self.should_stop():
            return self.stop_output(model)
        if self.exhausted or self.used() >= self.budget:
            if not self.exhausted:
                self.exhausted = True
                if self.on_exhausted is not None:
                    self.on_exhausted()
            return self.stop_output(model)

        conv = _conversation(messages)
        fps = [_fingerprint(m) for m in conv]
        own, is_main = self._classify(conv, fps)
        if not own:
            self.foreign_calls += 1
            first = conv[0].text[:300] if conv else ""
            transcript().info(
                {
                    "bridge_of": self.agent,
                    "reason": "model call does not continue this agent's conversation",
                    "first_user_text": first,
                    "messages": len(conv),
                },
                source="swarm.foreign_turn",
            )
            return None

        self._remember(conv, fps, is_main)
        if not (self.notice and is_main and self.bus is not None):
            return None

        digest = self.bus.digest(self.agent)
        if digest:
            self.digests.append((len(messages), digest))
        if not self.digests:
            return None
        patched = list(messages)
        for position, text in sorted(self.digests, reverse=True):
            if position <= len(patched):
                patched.insert(position, ChatMessageUser(content=text))
        return GenerateInput(input=patched, tools=tools, tool_choice=tool_choice, config=config)

    def _classify(self, conv: list[ChatMessage], fps: list[str]) -> tuple[bool, bool]:
        """(is this one of the agent's own conversations?, is it the main one?)."""
        if not conv:
            return True, False
        # Same first user message and (once there is one) same first reply as the main
        # conversation. Agents with the same prompt share the first message, so the
        # first reply is what tells them apart.
        n = min(2, len(fps), len(self.main or []))
        if self.main is not None and n >= 1 and fps[:n] == self.main[:n]:
            return True, True
        for known in self.conversations:
            if len(fps) >= 2 and len(known) >= 2 and fps[:2] == known[:2]:
                return True, False
        first = conv[0].text.strip()
        if self.main is None and self.prompt.strip()[:500] in first:
            return True, True
        # a new conversation the agent started itself: a subagent, a summary of its own
        # history, or a background call quoting its own work
        if any(arg and arg in first for arg in self.tool_args):
            return True, False
        if self.prompt.strip()[:200] in "\n".join(m.text for m in conv):
            return True, False
        return False, False

    def _remember(self, conv: list[ChatMessage], fps: list[str], is_main: bool) -> None:
        if is_main:
            self.main = fps
        elif fps and not any(fps[:2] == k[:2] for k in self.conversations):
            self.conversations.append(fps)
        for m in conv:
            if isinstance(m, ChatMessageAssistant) and m.tool_calls:
                for c in m.tool_calls:
                    for v in c.arguments.values():
                        if isinstance(v, str) and len(v) >= 20:
                            self.tool_args.add(v.strip()[:500])
