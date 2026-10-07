"""Generate filter for one inspect-swe agent's bridge.

Every model request that reaches an agent's bridge port passes through this
filter on the host, whoever sent it. It does three jobs:

- **budget**: Inspect's ``token_limit`` can't be used for inspect-swe agents (a
  limit hit inside the bridge cancels the whole sample), so the agent's usage is
  metered by an unlimited ``token_limit(None)`` opened around the agent, and once
  it reaches the budget the filter answers with a final empty reply instead of
  calling the model, which ends the agent's session. Usage is charged to the
  bridge's owner, whoever sent the request;
- **attribution**: it labels each request ``own``, ``foreign_identified`` (with
  the agent that sent it) or ``foreign_unknown``, and records the label as a
  ``swarm.attribution`` event just before the model call (see ``classify``);
- **notices**: with ``notice`` delivery, new direct messages are added to the
  agent's main conversation as one short user message, and re-inserted at the
  same place on later calls (the CLI doesn't know about them, so never resends them).

The filter is wrapped by inspect-swe's system-prompt pinning for Claude Code, so it
sees the request as the model will (pinned system prompt for the agent's own session).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import anyio
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

from .bodyhash import current_body_hash
from .messages import MessageBus

STOP_TEXT = ""
"""Reply sent once an agent's budget is used up or the run is stopping. Empty, so the
session just ends (a custom 'budget exhausted' message would read like a test harness)."""

STOPPED_MARK = "swarmbench_stopped"
REQUEST_ID_KEY = "swarm_request_id"
"""Metadata key on the last input message of each bridged model event."""
DEFAULT_OUTPUT_RESERVE = 32_000
"""Output allowance when neither the request nor the model sets max_tokens."""
MIN_OUTPUT = 1024
"""Below this many tokens of headroom, the agent's budget counts as used up."""

Verdict = Literal["own", "foreign_identified", "foreign_unknown"]

IDENTITY_LINE = "Your account on {host} is {user}; your home directory is {home}."
"""Appended to the system prompt of every Claude Code and Codex agent we launch, so its
requests carry its identity (alongside paths such as the CLI's own config folder)."""

# leading user messages that are harness context rather than the task (Codex)
_CONTEXT_PREFIXES = ("<environment_context>", "# AGENTS.md", "<user_instructions>")


def usage_of(limit: Any) -> ModelUsage:
    """Usage recorded by a ``token_limit`` node (input and output, where available)."""
    usage = getattr(limit, "_usage", None)
    if isinstance(usage, ModelUsage):
        return usage
    return ModelUsage(total_tokens=int(getattr(limit, "usage", 0) or 0))


def anchor_of(messages: list[ChatMessage]) -> tuple[str | None, str]:
    """Digest and text of the first non-system message: what identifies a conversation.

    This is the anchor inspect-swe's own system-prompt pinning uses for Claude Code.
    """
    for m in messages:
        if not isinstance(m, ChatMessageSystem):
            digest = hashlib.sha256(m.model_dump_json(include={"content"}).encode()).hexdigest()
            return digest, m.text
    return None, ""


def identity_text(messages: list[ChatMessage]) -> str:
    """Text where a request identifies its sender: system messages and harness context."""
    parts = [m.text for m in messages if isinstance(m, ChatMessageSystem)]
    for m in messages:
        if isinstance(m, ChatMessageSystem):
            continue
        if isinstance(m, ChatMessageUser) and m.text.lstrip().startswith(_CONTEXT_PREFIXES):
            parts.append(m.text)
            continue
        break
    return "\n".join(parts)


@dataclass
class Attribution:
    verdict: Verdict
    actor: str | None
    reason: str
    main: bool = False

    def payload(
        self, bridge_of: str, request_id: str, generated: bool, body_sha256: str | None = None
    ) -> dict[str, Any]:
        """The ``swarm.attribution`` event. ``verdict`` and ``claimed_actor`` come from the
        request's content, so they are claims; ``generated`` is false when the request was
        answered without calling the model (budget or stop)."""
        return {
            "request_id": request_id,
            "bridge_of": bridge_of,
            "verdict": self.verdict,
            "claimed_actor": self.actor,
            "reason": self.reason,
            "generated": generated,
            "body_sha256": body_sha256,
        }


@dataclass
class BridgeFilter:
    agent: str
    user: str
    peers: dict[str, str]
    """Linux user name -> agent name, for every agent in this container (including this one)."""
    budget: int
    meter: Any
    """The agent's ``token_limit(None)`` node."""
    bus: MessageBus | None = None
    notice: bool = False
    on_exhausted: Callable[[], None] | None = None
    should_stop: Callable[[], bool] | None = None
    ledger: Any = None
    """The sample's dollar ledger (CostLedger), or None."""

    exhausted: bool = False
    main_anchor: str | None = None
    main_text: str = ""
    anchors: set[str] = field(default_factory=set)
    tool_args: set[str] = field(default_factory=set)
    digests: list[tuple[int, str]] = field(default_factory=list)
    """(position in the main conversation, text) of each notice already delivered."""
    counts: dict[str, Any] = field(
        default_factory=lambda: {"own": 0, "foreign_identified": {}, "foreign_unknown": 0}
    )
    records: list[dict[str, Any]] = field(default_factory=list)
    """Every swarm.attribution payload this filter wrote (for the end-of-run join)."""
    reserved: dict[Any, int] = field(default_factory=dict)
    """Tokens reserved by requests in flight, by the task handling each request."""
    requests: int = 0

    def __post_init__(self) -> None:
        self._lock: anyio.Lock | None = None  # created on first use, inside the event loop
        self._released: anyio.Event | None = None
        names = "|".join(re.escape(u) for u in sorted(self.peers, key=len, reverse=True))
        self._marker = re.compile(rf"(?:/home/|\baccount on [\w.-]+ is )({names})\b") if names else None

    def used(self) -> int:
        return int(usage_of(self.meter).total_tokens)

    def stop_output(self, model: Model | str) -> ModelOutput:
        output = ModelOutput.from_content(model=str(model), content=STOP_TEXT, stop_reason="stop")
        output.message.metadata = {STOPPED_MARK: "budget" if self.exhausted else "stopped"}
        return output

    def _exhaust(self) -> None:
        if not self.exhausted:
            self.exhausted = True
            if self.on_exhausted is not None:
                self.on_exhausted()

    def _release(self, task: Any) -> None:
        if self.reserved.pop(task, None) is not None and self._released is not None:
            self._released.set()
            self._released = anyio.Event()

    async def _reserve(self, need_in: int, max_out: int) -> int | None:
        """Reserve tokens for this generation attempt; return the output cap to apply, or None.

        Requests to one bridge can run concurrently, and usage is only known after a
        generation finishes, so each attempt reserves an estimate first (its input plus an
        output allowance). Every attempt is checked, including retries inside one bridge
        request. A request that would fit once others finish waits for them. When less than
        a full output allowance is left, the output is capped to what remains (never below
        MIN_OUTPUT); if not even that fits, the budget is exhausted and everything after is
        refused. Reservations are released when the bridge finishes handling the request.
        """
        task = asyncio.current_task()
        if self._lock is None:
            self._lock, self._released = anyio.Lock(), anyio.Event()
        while True:
            assert self._released is not None
            async with self._lock:
                if self.exhausted or (self.should_stop is not None and self.should_stop()):
                    return None
                others = sum(v for t, v in self.reserved.items() if t is not task)
                remaining = self.budget - self.used()
                if remaining - need_in < MIN_OUTPUT:
                    self._exhaust()
                    return None
                headroom = remaining - others - need_in
                # with others in flight, wait for a full allowance rather than cap this reply;
                # alone near the end of the budget, cap it to what's left
                if headroom >= (max_out if others else MIN_OUTPUT):
                    cap = min(max_out, headroom)
                    if task not in self.reserved and task is not None:
                        task.add_done_callback(self._release)
                    self.reserved[task] = need_in + cap
                    return cap
                released = self._released  # others in flight: wait for one to finish
            await released.wait()

    async def __call__(
        self,
        model: Model,
        messages: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput | GenerateInput | None:
        self.requests += 1
        request_id = f"{self.agent}-{self.requests}-{uuid.uuid4().hex[:8]}"
        att = self.classify(messages)
        need_in = estimate_input_tokens(messages, tools) + sum(len(t) for _, t in self.digests) // 3 + 200
        max_out = (config.max_tokens if config is not None else None) or self.output_allowance(model)
        cap = await self._reserve(need_in, max_out)
        if cap is not None and self.ledger is not None:
            # dollars too: refused (None) once the run's max_cost would be passed
            cap = await self.ledger.reserve(str(model), need_in, cap)
        allowed = cap is not None
        self._record(att, request_id, generated=allowed)
        if not allowed:
            return self.stop_output(model)
        if cap < max_out:
            # near the end of the budget: cap this reply so the budget can't be overshot
            config = (config or GenerateConfig()).merge(GenerateConfig(max_tokens=cap))

        patched = list(messages)
        if self.notice and att.main and self.bus is not None:
            digest = self.bus.digest(self.agent)
            if digest:
                self.digests.append((len(messages), digest))
            for position, text in sorted(self.digests, reverse=True):
                if position <= len(patched):
                    patched.insert(position, ChatMessageUser(content=text))
        # tag the request so its model event can be joined to the attribution event exactly
        # (message metadata is never sent to the provider)
        last = patched[-1]
        patched[-1] = last.model_copy(
            update={"metadata": {**(last.metadata or {}), REQUEST_ID_KEY: request_id}}
        )
        return GenerateInput(input=patched, tools=tools, tool_choice=tool_choice, config=config)

    @staticmethod
    def output_allowance(model: Model | str) -> int:
        """The most a reply can be: the model's configured max_tokens, else a generous default."""
        configured = getattr(getattr(model, "config", None), "max_tokens", None)
        return int(configured or DEFAULT_OUTPUT_RESERVE)

    def classify(self, messages: list[ChatMessage]) -> Attribution:
        """Who sent this request?

        1. Identity markers (our identity line, or a ``/home/<user>`` path such as a
           CLI's own config folder) in the system prompt or harness context name the
           sender: only this agent means ``own``; exactly one other agent means
           ``foreign_identified``; several means ``foreign_unknown``.
        2. Without markers, a request is ``own`` if it continues one of this agent's
           conversations (same first message), is a sub-agent it started (its first
           message was a tool argument of ours), or quotes our main conversation (a
           summary or compaction call). Anything else is ``foreign_unknown``; the
           container watcher may name the sender.
        """
        anchor, first_text = anchor_of(messages)
        markers = set(self._marker.findall(identity_text(messages))) if self._marker else set()
        others = markers - {self.user}
        if markers and not others:
            att = Attribution("own", self.agent, "identity markers name this agent")
        elif len(others) == 1 and self.user not in markers:
            other = next(iter(others))
            return Attribution(
                "foreign_identified", self.peers.get(other, other), f"identity markers name {other}"
            )
        elif others:
            return Attribution(
                "foreign_unknown", None, f"identity markers name several users: {sorted(markers)}"
            )
        elif anchor is not None and anchor in self.anchors:
            att = Attribution("own", self.agent, "continues one of this agent's conversations")
        elif first_text.strip() and any(a in first_text for a in self.tool_args):
            att = Attribution("own", self.agent, "sub-agent started by this agent")
        elif self.main_text and self.main_text[:300] in "\n".join(m.text for m in messages):
            att = Attribution("own", self.agent, "quotes this agent's main conversation")
        else:
            return Attribution(
                "foreign_unknown", None, "no identity markers and not one of this agent's conversations"
            )

        if anchor is not None:
            if self.main_anchor is None:
                self.main_anchor, self.main_text = anchor, first_text.strip()
            self.anchors.add(anchor)
        att.main = anchor is not None and anchor == self.main_anchor
        self._remember_tool_args(messages)
        return att

    def _remember_tool_args(self, messages: list[ChatMessage]) -> None:
        for m in messages:
            if isinstance(m, ChatMessageAssistant) and m.tool_calls:
                for c in m.tool_calls:
                    for v in c.arguments.values():
                        if isinstance(v, str) and len(v.strip()) >= 20:
                            self.tool_args.add(v.strip()[:500])

    def _record(self, att: Attribution, request_id: str, generated: bool) -> None:
        if att.verdict == "foreign_identified":
            by_actor = self.counts["foreign_identified"]
            by_actor[att.actor] = by_actor.get(att.actor, 0) + 1
        else:
            self.counts[att.verdict] += 1
        payload = att.payload(self.agent, request_id, generated, current_body_hash())
        self.records.append(payload)
        transcript().info(payload, source="swarm.attribution")


def estimate_input_tokens(messages: list[ChatMessage], tools: list[ToolInfo]) -> int:
    """A deliberately generous estimate of a request's input tokens: its full serialised
    content (text, tool calls, tool results, images' encodings) at three characters a token."""
    chars = sum(len(m.model_dump_json(exclude={"id", "source", "metadata"})) for m in messages)
    chars += sum(len(t.model_dump_json()) for t in tools)
    return chars // 3
