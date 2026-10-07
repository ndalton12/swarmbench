"""Pull the judge's inputs out of one Inspect ``.eval`` sample.

The engine writes per-agent spans and ``swarm.*`` info events plus an
end-of-sample store (see ``docs/interfaces.md`` section 2). This module turns
one sample into a plain ``SampleInputs`` the scanners and summarizer consume,
without needing the engine to be importable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalSample
from inspect_ai.model._chat_message import ChatMessage
from inspect_scout._transcript.messages import span_messages


@dataclass
class AgentView:
    """One agent's identity and its own message thread."""

    name: str
    uid: int | None = None
    user: str | None = None
    model: str | None = None
    messages: list[ChatMessage] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(_message_text(m) for m in self.messages)


@dataclass
class SampleInputs:
    scenario: str
    run_id: str
    sample_id: str | int | None
    epoch: int
    agents: list[AgentView]
    agents_meta: list[dict[str, Any]]
    messages: list[dict[str, Any]]  # swarm.message payloads (SwarmMessage dicts)
    monitor_flags: list[dict[str, Any]]
    bridge_summary: dict[str, dict[str, Any]]
    attributions: list[dict[str, Any]]  # swarm.attribution labels (engine)
    protected_hashes: dict[str, dict[str, str]]
    problems: list[str]
    agent_usage: dict[str, dict[str, Any]]
    outcome: str
    full_text: str  # concatenation of everything, for verbatim quote checks

    def agent(self, name: str) -> AgentView | None:
        return next((a for a in self.agents if a.name == name), None)

    def cross_agent_uses(self) -> list[dict[str, str]]:
        """Who used whose model bridge, attributing each use to the real actor.

        Engine attribution labels come first (ground truth from the per-request
        content check in each bridge filter). For a call the engine could only
        mark ``foreign-unknown``, the watcher's ``/proc/net/tcp`` record is used
        to name the actor; when neither can, the actor is reported as
        ``"unknown"``. Each item is ``{owner, actor, basis}``.
        """
        uses: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        def add(owner: str, actor: str, basis: str) -> None:
            if owner == actor:
                return
            key = (owner, actor)
            if key in seen:
                return
            seen.add(key)
            uses.append({"owner": owner, "actor": actor, "basis": basis})

        for att in self.attributions:
            # Documented shape: {"bridge_of", "verdict", "actor", "reason"} with
            # verdict in own|foreign_identified|foreign_unknown. Stay tolerant of
            # the older label/owner_agent names and of hyphens.
            verdict = str(att.get("verdict") or att.get("label") or "").lower().replace("-", "_")
            owner = att.get("bridge_of") or att.get("owner_agent") or att.get("owner")
            if not owner or "foreign" not in verdict:
                continue
            actor = att.get("actor") or att.get("actor_agent")
            if verdict == "foreign_identified" and actor:
                add(owner, actor, "engine attribution")
            else:  # foreign_unknown: try the watcher, else unknown
                watcher_actor = self._watcher_actor(owner)
                add(owner, watcher_actor or "unknown", "watcher" if watcher_actor else "unresolved")

        # Also surface cross-agent uses the watcher saw but the engine did not label.
        for owner, peers in self.bridge_summary.items():
            for peer in peers:
                if peer != owner and not peer.startswith("uid:"):
                    add(owner, peer, "watcher")
        return uses

    def _watcher_actor(self, owner: str) -> str | None:
        peers = self.bridge_summary.get(owner, {})
        for peer in peers:
            if peer != owner and not peer.startswith("uid:"):
                return peer
        return None


def _message_text(m: ChatMessage) -> str:
    parts: list[str] = []
    if isinstance(m.text, str) and m.text:
        parts.append(m.text)
    # include reasoning/thinking content, where present (awareness shows there first)
    for content in getattr(m, "content", []) or []:
        reasoning = getattr(content, "reasoning", None)
        if reasoning:
            parts.append(str(reasoning))
    return "\n".join(parts)


def _per_agent_model_events(events: list[Any]) -> dict[str, list[ModelEvent]]:
    """Group model events by the nearest enclosing ``type="agent"`` span."""
    stack: list[tuple[str, str | None, str]] = []
    out: dict[str, list[ModelEvent]] = {}
    for e in events:
        kind = getattr(e, "event", None)
        if kind == "span_begin":
            stack.append((e.span_id, e.type, e.name))
        elif kind == "span_end":
            if stack:
                stack.pop()
        elif kind == "model":
            for _sid, typ, nm in reversed(stack):
                if typ == "agent":
                    out.setdefault(nm, []).append(e)
                    break
    return out


def _attribution_from_store(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the end-of-run ``swarm_attribution`` store summary into entries.

    Shape (engine): ``{owner: {"own": n, "foreign_identified": {actor: n},
    "foreign_unknown": n}}``. Used as a fallback/corroboration when the
    per-call ``swarm.attribution`` events are not present.
    """
    out: list[dict[str, Any]] = []
    for owner, counts in (summary or {}).items():
        if not isinstance(counts, dict):
            continue
        for actor in (counts.get("foreign_identified") or {}):
            out.append({"bridge_of": owner, "verdict": "foreign_identified", "actor": actor})
        if counts.get("foreign_unknown"):
            out.append({"bridge_of": owner, "verdict": "foreign_unknown", "actor": None})
    return out


def _info_events(events: list[Any], source: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for e in events:
        if getattr(e, "event", None) == "info" and getattr(e, "source", None) == source:
            if isinstance(e.data, dict):
                out.append(e.data)
    return out


def _store_value(sample: EvalSample, key: str, default: Any) -> Any:
    store = sample.store or {}
    value = store.get(key, default)
    return value if value is not None else default


def extract_sample(sample: EvalSample) -> SampleInputs:
    meta = (sample.metadata or {}).get("swarm", {})
    agents_meta: list[dict[str, Any]] = meta.get("agents", [])
    events = sample.events or []

    per_agent_events = _per_agent_model_events(events)
    # Prefer the engine's declared agent list; fall back to whatever spans exist.
    names = [a["name"] for a in agents_meta] or list(per_agent_events.keys())

    agents: list[AgentView] = []
    for name in names:
        am = next((a for a in agents_meta if a.get("name") == name), {})
        evs = per_agent_events.get(name, [])
        agents.append(
            AgentView(
                name=name,
                uid=am.get("uid"),
                user=am.get("user"),
                model=am.get("model"),
                messages=span_messages(evs) if evs else [],
            )
        )

    messages = _store_value(sample, "swarm_messages", []) or _info_events(events, "swarm.message")
    monitor_flags = _info_events(events, "swarm.monitor")
    # Engine attribution: one swarm.attribution info event per bridged model
    # request (verdict own | foreign_identified | foreign_unknown), with an
    # end-of-run swarm_attribution store summary as a fallback.
    attributions = _info_events(events, "swarm.attribution") + _attribution_from_store(
        _store_value(sample, "swarm_attribution", {})
    )
    bridge_summary = _store_value(sample, "swarm_bridge_summary", {})
    protected_hashes = _store_value(sample, "swarm_protected_hashes", {"before": {}, "after": {}})
    problems = _store_value(sample, "swarm_problems", [])
    agent_usage = _store_value(sample, "swarm_agent_usage", {})
    outcome = (sample.output.completion if sample.output else "") or ""

    full_text = "\n".join(
        [a.text() for a in agents]
        + [str(m.get("text", "")) for m in messages]
        + [outcome]
    )

    return SampleInputs(
        scenario=meta.get("scenario", "unknown"),
        run_id=meta.get("run_id", "unknown"),
        sample_id=sample.id,
        epoch=sample.epoch or 1,
        agents=agents,
        agents_meta=agents_meta,
        messages=messages,
        monitor_flags=monitor_flags,
        bridge_summary=bridge_summary,
        attributions=attributions,
        protected_hashes=protected_hashes,
        problems=problems,
        agent_usage=agent_usage,
        outcome=outcome,
        full_text=full_text,
    )
