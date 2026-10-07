"""Pull the judge's inputs out of one Inspect ``.eval`` sample.

The engine writes per-agent spans and ``swarm.*`` info events plus an
end-of-sample store (see ``docs/interfaces.md`` section 2). This module turns
one sample into a plain ``SampleInputs`` the scanners and summarizer consume,
without needing the engine to be importable.

Three things matter for getting attribution right:

- **Spans by id.** Agents run concurrently, so events from different agents
  interleave in the log. Each event is resolved to its agent through its own
  ``span_id`` and the span tree (``id``/``parent_id``), never by the order of
  begin/end events. Nested spans (a subagent, react's own agent span) belong
  to the outermost declared agent that contains them.
- **Compaction.** Compaction events are kept with each agent's model events,
  so the conversation before a compaction is still scanned.
- **Foreign turns.** When agent A uses agent B's bridge, A's model calls land
  in B's span. The engine emits a ``swarm.attribution`` event just before each
  bridged model call. Calls labelled ``foreign_identified`` are scanned as A
  acting through B's bridge (not as B's behaviour); ``foreign_unknown`` calls
  are scanned separately as an unidentified agent, named from the watcher's
  connection records only when exactly one other agent was connected at that
  moment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from inspect_ai.log import EvalSample
from inspect_ai.model._chat_message import ChatMessage
from inspect_scout._transcript.messages import span_messages

UNKNOWN = "unknown"
WATCHER_MATCH_SECONDS = 10.0


@dataclass
class AgentView:
    """One agent's own message thread, or its turns through another's bridge."""

    name: str
    uid: int | None = None
    user: str | None = None
    model: str | None = None
    messages: list[ChatMessage] = field(default_factory=list)
    acting_as: str | None = None
    """Set for turns made through another agent's bridge: whose bridge it was."""
    basis: str = ""
    """How the turns were attributed (for foreign views)."""
    span_event_id: str | None = None
    """Log event id of the agent span these turns sit in (the owner's span for foreign
    turns), so a Scout result can link straight to it."""

    @property
    def label(self) -> str:
        if self.acting_as:
            return f"{self.name} (via {self.acting_as}'s bridge)"
        return self.name

    def text(self) -> str:
        return "\n".join(message_text(m) for m in self.messages)


@dataclass
class SampleInputs:
    scenario: str
    run_id: str
    sample_id: str | int | None
    epoch: int
    agents: list[AgentView]
    """Each declared agent's own turns."""
    foreign: list[AgentView]
    """Turns made through another agent's bridge (see the module docstring)."""
    agents_meta: list[dict[str, Any]]
    messages: list[dict[str, Any]]  # swarm.message payloads (SwarmMessage dicts)
    monitor_flags: list[dict[str, Any]]
    bridge_summary: dict[str, dict[str, Any]]
    bridge_uses: list[dict[str, str]]
    """``{owner, actor, kind, basis}``: kind is ``model_calls`` or ``connection``."""
    protected_hashes: dict[str, dict[str, str]]
    problems: list[str]
    agent_usage: dict[str, dict[str, Any]]
    outcome: str
    workspace_changes: list[dict[str, Any]] = field(default_factory=list)
    """From ``swarm_workspace_diff``: ``{team, path, change, owner_uid, agent, ...}`` per changed file."""
    workspace_total: int = 0
    workspace_gaps: list[str] = field(default_factory=list)
    transcript_id: str | None = None
    """Scout's id for this sample's transcript (the sample uuid)."""
    message_event_ids: dict[Any, str] = field(default_factory=dict)
    """Swarm message id -> id of the ``swarm.message`` event that logged it."""

    def owner_name(self, uid: Any, agent: str | None = None) -> str:
        """Plain description of a file owner's uid: the agent, or the bare uid."""
        if uid is None:
            return "owner unknown"
        if agent:
            return f"uid {uid} ({agent})"
        for a in self.agents_meta:
            if a.get("uid") == uid:
                return f"uid {uid} ({a.get('name')})"
        return f"uid {uid} (not an agent)"

    def agent(self, name: str) -> AgentView | None:
        return next((a for a in self.agents if a.name == name), None)

    def views(self) -> list[AgentView]:
        """Everything the per-agent scanners read: own turns, then foreign turns."""
        return self.agents + self.foreign

    def team_text(self) -> str:
        return "\n".join(render_message(m) for m in self.messages)

    def all_text(self) -> str:
        return "\n".join([v.text() for v in self.views()] + [self.team_text(), self.outcome])


def message_text(m: ChatMessage) -> str:
    """Text the judge sees for one message: content, reasoning and tool-call arguments."""
    parts: list[str] = []
    if isinstance(m.text, str) and m.text:
        parts.append(m.text)
    for content in getattr(m, "content", []) or []:
        reasoning = getattr(content, "reasoning", None)
        if reasoning:
            parts.append(str(reasoning))
    for call in getattr(m, "tool_calls", None) or []:
        for value in (call.arguments or {}).values():
            parts.append(value if isinstance(value, str) else str(value))
    return "\n".join(parts)


def render_message(m: dict[str, Any]) -> str:
    """A swarm message with its *authenticated* sender first.

    The sender comes from the bus caller or the board file's owner. A name the
    text signs itself with is shown separately as an unverified claim, so a
    forged signature can't put words in the victim's mouth.
    """
    sender = m.get("sender", "?")
    to = m.get("to", "all")
    extra = []
    claimed = m.get("claimed_sender")
    if claimed and claimed != sender:
        extra.append(f"signed as {claimed} - unverified claim")
    via = m.get("via_bridge_of")
    if via and via != sender:
        extra.append(f"sent through {via}'s bridge")
    note = f" ({'; '.join(extra)})" if extra else ""
    return f"{sender}{note} -> {to}: {m.get('text', '')}"


# ---------------------------------------------------------------------------


def _span_tree(events: list[Any]) -> dict[str, tuple[str, str | None, str | None]]:
    """span id -> (name, type, parent id)."""
    spans: dict[str, tuple[str, str | None, str | None]] = {}
    for e in events:
        if getattr(e, "event", None) == "span_begin":
            spans[e.id] = (e.name, e.type, e.parent_id)
    return spans


def _owner_of(
    span_id: str | None,
    spans: dict[str, tuple[str, str | None, str | None]],
    declared: set[str],
) -> str | None:
    """The outermost declared agent (or outermost ``type="agent"`` span) containing a span."""
    owner: str | None = None
    seen: set[str] = set()
    while span_id and span_id in spans and span_id not in seen:
        seen.add(span_id)
        name, typ, parent = spans[span_id]
        if (declared and name in declared) or (not declared and typ == "agent"):
            owner = name  # keep walking up: the outermost match wins
        span_id = parent
    return owner


def _verdict(att: dict[str, Any]) -> str:
    return str(att.get("verdict") or att.get("label") or "").lower().replace("-", "_")


def _bridge_events(events: list[Any]) -> list[tuple[datetime | None, dict[str, Any]]]:
    out = []
    for e in events:
        if getattr(e, "event", None) == "info" and getattr(e, "source", None) == "swarm.bridge":
            if isinstance(e.data, dict):
                out.append((_parse_time(e.data.get("time")) or getattr(e, "timestamp", None), e.data))
    return out


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _watcher_actor_at(
    owner: str, when: datetime | None, bridge_events: list[tuple[datetime | None, dict[str, Any]]]
) -> str | None:
    """The one other agent connected to ``owner``'s bridge near ``when``, if exactly one."""
    if when is None:
        return None
    peers = set()
    for t, data in bridge_events:
        if data.get("owner_agent") != owner or t is None or data.get("state") == "attempt":
            continue
        if abs((t - when).total_seconds()) <= WATCHER_MATCH_SECONDS:
            # an unmapped uid is a candidate too: it makes the match ambiguous
            peers.add(data.get("peer_agent") or f"uid:{data.get('peer_uid')}")
    if len(peers) == 1:
        (only,) = peers
        return None if only.startswith("uid:") else only
    return None


def _split_turns(
    events: list[Any],
    spans: dict[str, tuple[str, str | None, str | None]],
    declared: set[str],
    bridge_events: list[tuple[datetime | None, dict[str, Any]]],
) -> tuple[dict[str, dict[str, list[Any]]], dict[tuple[str, str, str], list[Any]], list[dict[str, str]]]:
    """Own events per agent, foreign events per (actor, owner, basis), and the uses found."""
    own: dict[str, dict[str, list[Any]]] = {}  # owner -> span id -> events (one conversation each)
    foreign: dict[tuple[str, str, str], list[Any]] = {}
    uses: list[dict[str, str]] = []
    pending: dict[str, tuple[dict[str, Any], datetime | None]] = {}
    for e in events:
        kind = getattr(e, "event", None)
        if kind not in ("model", "compaction", "info"):
            continue
        owner = _owner_of(getattr(e, "span_id", None), spans, declared)
        if kind == "info":
            if getattr(e, "source", None) == "swarm.attribution" and isinstance(e.data, dict):
                bridge_of = e.data.get("bridge_of") or owner
                if bridge_of:
                    pending[bridge_of] = (e.data, getattr(e, "timestamp", None))
            continue
        if owner is None:
            continue
        conversation = getattr(e, "span_id", None) or ""
        if kind == "compaction":
            own.setdefault(owner, {}).setdefault(conversation, []).append(e)
            continue
        att, when = pending.pop(owner, (None, None))
        verdict = _verdict(att) if att else "own"
        if verdict == "foreign_identified" and att and att.get("actor") and att["actor"] != owner:
            key = (att["actor"], owner, "engine attribution")
        elif verdict == "foreign_unknown":
            named = _watcher_actor_at(owner, when, bridge_events)
            key = (named, owner, "watcher connection at that moment") if named else (UNKNOWN, owner, "unresolved")
        else:
            own.setdefault(owner, {}).setdefault(conversation, []).append(e)
            continue
        if key not in foreign:
            uses.append({"owner": owner, "actor": key[0], "kind": "model_calls", "basis": key[2]})
        foreign.setdefault(key, []).append(e)
    return own, foreign, uses


def _conversations(groups: list[list[Any]]) -> list[ChatMessage]:
    """Messages from several separate conversations, in order.

    ``span_messages`` rebuilds one conversation from its last model call (plus
    compactions), so each conversation is rebuilt on its own and then merged.
    Repeated history (the same role and text) is kept once.
    """
    out: list[ChatMessage] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        if not any(getattr(e, "event", None) == "model" for e in group):
            continue
        for m in span_messages(group):
            key = (m.role, message_text(m))
            if key not in seen:
                seen.add(key)
                out.append(m)
    return out


def _store_summary_uses(summary: dict[str, Any]) -> list[dict[str, str]]:
    """Uses from the end-of-run ``swarm_attribution`` summary (fallback only).

    Shape (engine): ``{owner: {"own": n, "foreign_identified": {actor: n},
    "foreign_unknown": n}}``.
    """
    out: list[dict[str, str]] = []
    for owner, counts in (summary or {}).items():
        if not isinstance(counts, dict):
            continue
        for actor in counts.get("foreign_identified") or {}:
            if actor != owner:
                out.append({"owner": owner, "actor": actor, "kind": "model_calls", "basis": "engine attribution"})
        if counts.get("foreign_unknown"):
            out.append({"owner": owner, "actor": UNKNOWN, "kind": "model_calls", "basis": "unresolved"})
    return out


def workspace_changes(raw: Any) -> list[dict[str, Any]]:
    """Normalise the engine's ``swarm_workspace_diff`` into a flat list.

    Engine shape: ``{team: {"changes": [{"path", "change", "type", "uid",
    "agent", "sha_before", "sha_after", "size_before", "size_after",
    "unverified"}], "total_changes", "truncated", "notes", ...}}``. Each entry
    gains ``team`` and ``owner_uid`` (the final owner's uid; None when deleted).
    Simpler shapes (``{team: {path: {...}}}`` or a plain list) are also read.
    """
    out: list[dict[str, Any]] = []

    def add(team: str | None, path: str | None, info: Any) -> None:
        info = info if isinstance(info, dict) else {"change": info}
        path = path or info.get("path")
        if not path:
            return
        out.append(
            {
                **info,
                "team": team or info.get("team"),
                "path": str(path),
                "change": str(info.get("change") or info.get("status") or "changed"),
                "owner_uid": info.get("owner_uid", info.get("uid")),
            }
        )

    if isinstance(raw, list):
        for entry in raw:
            add(None, None, entry)
    elif isinstance(raw, dict):
        for team, value in raw.items():
            if isinstance(value, dict) and isinstance(value.get("changes"), list):
                for entry in value["changes"]:
                    add(team, None, entry)
            elif isinstance(value, dict):
                for path, info in value.items():
                    add(team, path, info)
            elif isinstance(value, list):
                for entry in value:
                    add(team, None, entry)
    return out


def workspace_summary(raw: Any) -> tuple[int, list[str]]:
    """Total changed files (the engine's count, which survives truncation) and
    plain notes about teams whose comparison hit a cap."""
    total, gaps = 0, []
    if isinstance(raw, dict):
        for team, value in raw.items():
            if isinstance(value, dict) and isinstance(value.get("changes"), list):
                total += int(value.get("total_changes") or len(value["changes"]))
                if value.get("truncated"):
                    gaps.append(f"workspace comparison for team {team} is incomplete (size or count caps hit)")
            elif isinstance(value, (dict, list)):
                total += len(value)
    elif isinstance(raw, list):
        total = len(raw)
    return total, gaps


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
    declared = {a["name"] for a in agents_meta if a.get("name")}

    spans = _span_tree(events)
    # each agent's outermost span: the first span_begin event with its name
    span_events: dict[str, str] = {}
    for e in events:
        if getattr(e, "event", None) == "span_begin" and e.name not in span_events and e.uuid:
            if (declared and e.name in declared) or (not declared and e.type == "agent"):
                span_events[e.name] = e.uuid
    bridge_events = _bridge_events(events)
    own, foreign_events, uses = _split_turns(events, spans, declared, bridge_events)

    names = [a["name"] for a in agents_meta] or list(own.keys())
    agents: list[AgentView] = []
    for name in names:
        am = next((a for a in agents_meta if a.get("name") == name), {})
        agents.append(
            AgentView(
                name=name,
                uid=am.get("uid"),
                user=am.get("user"),
                model=am.get("model"),
                span_event_id=span_events.get(name),
                messages=_conversations(list(own.get(name, {}).values())),
            )
        )
    foreign = [
        # each foreign request is its own conversation
        AgentView(
            name=actor,
            acting_as=owner,
            basis=basis,
            messages=_conversations([[e] for e in evs]),
            span_event_id=span_events.get(owner),
        )
        for (actor, owner, basis), evs in foreign_events.items()
    ]

    # No per-call attribution events (older engine, or a summary-only log):
    # fall back to the end-of-run summary.
    if not uses:
        uses = _store_summary_uses(_store_value(sample, "swarm_attribution", {}))

    # Connections the watcher saw that no attribution explains: a connection
    # alone, not a confirmed model call.
    bridge_summary = _store_value(sample, "swarm_bridge_summary", {})
    explained = {(u["owner"], u["actor"]) for u in uses}
    for owner, peers in bridge_summary.items():
        for peer in peers:
            if peer != owner and not str(peer).startswith("uid:") and (owner, peer) not in explained:
                uses.append({"owner": owner, "actor": peer, "kind": "connection", "basis": "watcher"})

    messages = _store_value(sample, "swarm_messages", []) or _info_events(events, "swarm.message")
    diff = _store_value(sample, "swarm_workspace_diff", {})
    diff_total, diff_gaps = workspace_summary(diff)
    return SampleInputs(
        scenario=meta.get("scenario", "unknown"),
        run_id=meta.get("run_id", "unknown"),
        sample_id=sample.id,
        epoch=sample.epoch or 1,
        agents=agents,
        foreign=foreign,
        agents_meta=agents_meta,
        messages=messages,
        monitor_flags=_info_events(events, "swarm.monitor"),
        bridge_summary=bridge_summary,
        bridge_uses=uses,
        protected_hashes=_store_value(sample, "swarm_protected_hashes", {"before": {}, "after": {}}),
        problems=_store_value(sample, "swarm_problems", []),
        agent_usage=_store_value(sample, "swarm_agent_usage", {}),
        outcome=(sample.output.completion if sample.output else "") or "",
        workspace_changes=workspace_changes(diff),
        workspace_total=diff_total,
        workspace_gaps=diff_gaps,
        transcript_id=sample.uuid,
        message_event_ids={
            e.data.get("id"): e.uuid
            for e in events
            if getattr(e, "event", None) == "info"
            and getattr(e, "source", None) == "swarm.message"
            and isinstance(e.data, dict)
            and e.uuid
        },
    )
