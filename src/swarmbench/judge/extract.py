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
from typing import Any

from inspect_ai.log import EvalSample
from inspect_ai.model._chat_message import ChatMessage
from inspect_scout._transcript.messages import span_messages

from swarmbench.judge.attribution import (
    RELAY,
    UNKNOWN,
    UNVERIFIED,
    Request,
    gateway_index,
    parse_time,
    request_from_event,
    resolve,
    unjoined_cross_agent_requests,
)


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
    requests: list[Request] = field(default_factory=list)
    """Every bridged model request with its resolved sender (see judge.attribution)."""
    attribution_by_order: bool = False
    """True when requests had no ids and were paired with model calls by order."""
    refused_attempts: list[dict[str, Any]] = field(default_factory=list)
    """Direct bridge-port connections the relay refused."""
    unidentified_refusals: list[dict[str, Any]] = field(default_factory=list)
    """Gateway connections closed because the sender couldn't be identified: {bridge_of}.
    Not an attempt by a known agent."""
    agent_stops: list[dict[str, Any]] = field(default_factory=list)
    """Every agent stop: {agent, reason, time}. Reasons: finished, budget, stopped,
    "sample limit: ...", "crashed: ...", "terminated: ..."."""
    sample_error: str | None = None
    sample_limit: str | None = None
    """The Inspect sample limit that ended the run, if any (e.g. "time limit (7200)")."""
    started_at: Any = None
    """Time of the run's first event."""
    ended_because: str | None = None
    """The engine's plain line on why the run ended (sample metadata swarm_outcome.ended_because,
    or the swarm.run_end event's reason)."""
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

    file_excerpts: list[Any] = field(default_factory=list)
    """Changed workspace files (judge.workspace_files.FileExcerpt), filled in by the judge."""

    def files_text(self, owner: str | None = None) -> str:
        """Final contents and diffs of changed files (one agent's, or all), for quote checks."""
        return "\n".join(
            f"{e.final}\n{e.diff}" for e in self.file_excerpts if owner is None or e.owner == owner
        )

    def agent(self, name: str) -> AgentView | None:
        return next((a for a in self.agents if a.name == name), None)

    def views(self) -> list[AgentView]:
        """Everything the per-agent scanners read: own turns, then foreign turns."""
        return self.agents + self.foreign

    def team_text(self) -> str:
        return "\n".join(render_message(m) for m in self.messages)

    def all_text(self) -> str:
        return "\n".join([v.text() for v in self.views()] + [self.team_text(), self.outcome, self.files_text()])


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


def _intervals(sample_store: dict[str, Any], events: list[Any]) -> dict[str, list[list[Any]]]:
    """Connection records per bridge owner: the observer's interval summary, or
    (older logs) intervals built from the cross-agent ``swarm.bridge`` events."""
    stored = sample_store.get("swarm_bridge_intervals")
    if isinstance(stored, dict) and stored:
        return {k: [list(s) for s in v] for k, v in stored.items()}
    out: dict[str, list[list[Any]]] = {}
    for e in events:
        if getattr(e, "event", None) == "info" and getattr(e, "source", None) == "swarm.bridge":
            data = e.data if isinstance(e.data, dict) else {}
            when = parse_time(data.get("time")) or getattr(e, "timestamp", None)
            if data.get("owner_agent") and when is not None and data.get("state") != "attempt":
                t = when.timestamp()
                out.setdefault(data["owner_agent"], []).append(
                    [t, t, data.get("peer_uid"), data.get("peer_agent")]
                )
    return out


def _request_id_of(model_event: Any) -> str | None:
    """The engine puts the request id on the last input message's metadata."""
    inputs = getattr(model_event, "input", None) or []
    if not inputs:
        return None
    meta = getattr(inputs[-1], "metadata", None) or {}
    rid = meta.get("swarm_request_id")
    return str(rid) if rid is not None else None


def _view_key(req: Request) -> tuple[str, str, str]:
    return (req.actor, req.owner, req.status)


def _split_turns(
    events: list[Any],
    spans: dict[str, tuple[str, str | None, str | None]],
    declared: set[str],
    intervals: dict[str, list[list[Any]]],
    gateway: dict[str, list[tuple[float, float, str]]] | None = None,
    joined: dict[str, dict[str, Any]] | None = None,
    uid_names: dict[int, str] | None = None,
) -> tuple[dict[str, dict[str, list[Any]]], dict[tuple[str, str, str], list[Any]], list[Request], bool]:
    """Own events per agent, other agents' events per (actor, owner, status),
    every resolved request, and whether the pairing had to fall back to order.

    Each bridged model call is joined to its attribution event by request id.
    Older logs without request ids are paired by order (one pending label per
    bridge), which can mix up concurrent requests; the caller reports that.
    """
    own: dict[str, dict[str, list[Any]]] = {}  # owner -> span id -> events (one conversation each)
    foreign: dict[tuple[str, str, str], list[Any]] = {}
    by_id: dict[str, Request] = {}
    ordered: list[Request] = []
    for e in events:
        if getattr(e, "event", None) == "info" and getattr(e, "source", None) == "swarm.attribution":
            if isinstance(e.data, dict):
                owner = _owner_of(getattr(e, "span_id", None), spans, declared)
                req = request_from_event(e.data, getattr(e, "timestamp", None), owner)
                if req is not None and req.generated:
                    resolve(req, intervals, gateway, joined, uid_names)
                    ordered.append(req)
                    if req.request_id:
                        by_id[req.request_id] = req
    by_order = bool(ordered) and not by_id

    pending: dict[str, Request] = {}
    order_iter = iter(ordered)
    next_req = next(order_iter, None)
    session: dict[str, int] = {}  # wake-on-activity: each wake starts a new session
    for e in events:
        kind = getattr(e, "event", None)
        if kind == "info" and getattr(e, "source", None) == "swarm.agent_wake":
            woken = (e.data or {}).get("agent") if isinstance(e.data, dict) else None
            if woken:
                session[woken] = session.get(woken, 0) + 1
            continue
        if by_order and kind == "info" and getattr(e, "source", None) == "swarm.attribution":
            if next_req is not None:
                pending[next_req.owner] = next_req
                next_req = next(order_iter, None)
            continue
        if kind not in ("model", "compaction"):
            continue
        owner = _owner_of(getattr(e, "span_id", None), spans, declared)
        if owner is None:
            continue
        conversation = f"{getattr(e, 'span_id', None) or ''}#{session.get(owner, 0)}"
        req: Request | None = None
        if kind == "model":
            rid = _request_id_of(e)
            req = by_id.get(rid) if rid else (pending.pop(owner, None) if by_order else None)
        if req is None or req.actor == owner:
            own.setdefault(owner, {}).setdefault(conversation, []).append(e)
        else:
            foreign.setdefault(_view_key(req), []).append(e)
    return own, foreign, ordered, by_order


def _gateway_only_uses(
    gateway: dict[str, list[tuple[float, float, str]]],
    requests: list[Request],
    pairs: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Requests the gateway saw from another agent's uid that no attribution
    event accounts for (the gateway is authoritative, so these are facts).

    ``pairs`` comes from the engine's join (records no join references); without
    it (older logs), records are compared with the resolved requests instead.
    """
    counts: dict[tuple[str, str], int] = {}
    if pairs is not None:
        for key in pairs:
            counts[key] = counts.get(key, 0) + 1
    else:
        explained = {(r.owner, r.actor) for r in requests}
        for owner, recs in gateway.items():
            for _start, _end, sender in recs:
                if sender != owner and (owner, sender) not in explained:
                    counts[(owner, sender)] = counts.get((owner, sender), 0) + 1
    return [
        {
            "owner": o,
            "actor": a,
            "kind": "model_calls",
            "basis": RELAY,
            "claimed": None,
            "mismatch": False,
            "count": n,
        }
        for (o, a), n in counts.items()
    ]


def bridge_uses(requests: list[Request]) -> list[dict[str, Any]]:
    """Requests that went through another agent's bridge, or whose claimed sender
    disagrees with the evidence, grouped for the report."""
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in requests:
        if r.actor == r.owner and not r.mismatch:
            continue
        key = (r.owner, r.actor, r.status, r.claimed_actor, r.mismatch)
        g = groups.setdefault(
            key,
            {
                "owner": r.owner,
                "actor": r.actor,
                "kind": "model_calls",
                "basis": r.status,
                "claimed": r.claimed_actor,
                "mismatch": r.mismatch,
                "count": 0,
            },
        )
        g["count"] += 1
    return list(groups.values())


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


def _store_summary_uses(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Uses from the end-of-run ``swarm_attribution`` summary (fallback only).

    These are content claims with no per-request evidence, so they are always
    reported as unverified. Shape: ``{owner: {"own": n, "foreign_identified":
    {actor: n}, "foreign_unknown": n}}``.
    """
    out: list[dict[str, Any]] = []
    for owner, counts in (summary or {}).items():
        if not isinstance(counts, dict):
            continue
        for actor, n in (counts.get("foreign_identified") or {}).items():
            if actor != owner:
                out.append(
                    {
                        "owner": owner,
                        "actor": actor,
                        "kind": "model_calls",
                        "basis": UNVERIFIED,
                        "claimed": actor,
                        "mismatch": False,
                        "count": int(n or 1),
                    }
                )
        if counts.get("foreign_unknown"):
            out.append(
                {
                    "owner": owner,
                    "actor": UNKNOWN,
                    "kind": "model_calls",
                    "basis": UNVERIFIED,
                    "claimed": None,
                    "mismatch": False,
                    "count": int(counts["foreign_unknown"]),
                }
            )
    return out


def _gateway_refusals(records: list[Any], agents_meta: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gateway connections refused because the connecting uid couldn't be identified."""
    owners = {
        (a.get("sandbox"), a.get("bridge_port")): a["name"] for a in agents_meta if a.get("bridge_port")
    }
    out = []
    for r in records:
        if isinstance(r, dict) and r.get("t") == "refused":
            owner = owners.get((r.get("sandbox"), r.get("bridge_port")))
            out.append({"bridge_of": owner or f"port {r.get('bridge_port')}"})
    return out


def _refused_attempts(events: list[Any]) -> list[dict[str, Any]]:
    """Direct connections to a bridge port that the relay refused (interference attempts).

    Read tolerantly until the relay's event shape is final: any ``swarm.relay*``
    info event marked as refused.
    """
    out: list[dict[str, Any]] = []
    for e in events:
        source = str(getattr(e, "source", "") or "")
        if getattr(e, "event", None) != "info" or not source.startswith("swarm.relay"):
            continue
        data = e.data if isinstance(e.data, dict) else {}
        if source.endswith("refused") or data.get("refused") or data.get("event") == "refused":
            out.append(data)
    return out


NORMAL_STOP = "finished"


def _agent_stops(events: list[Any]) -> list[dict[str, Any]]:
    """Every ``swarm.agent_stopped`` event: {agent, reason, time}."""
    out = []
    for e in events:
        if getattr(e, "event", None) == "info" and getattr(e, "source", None) == "swarm.agent_stopped":
            data = e.data if isinstance(e.data, dict) else {}
            out.append(
                {
                    "agent": str(data.get("agent", "?")),
                    "reason": str(data.get("reason", "")),
                    "time": e.timestamp,
                }
            )
    return out


def _ended_because(sample: EvalSample, events: list[Any]) -> str | None:
    outcome = (sample.metadata or {}).get("swarm_outcome")
    if isinstance(outcome, dict) and outcome.get("ended_because"):
        return str(outcome["ended_because"])
    for data in reversed(_info_events(events, "swarm.run_end")):
        if data.get("reason"):
            return str(data["reason"])
    return None


def _sample_limit(sample: EvalSample) -> str | None:
    limit = getattr(sample, "limit", None)
    if limit is None:
        return None
    kind = getattr(limit, "type", None) or "sample"
    value = getattr(limit, "limit", None)
    return f"{kind} limit" + (f" ({value})" if value is not None else "")


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
                    gaps.append(
                        f"workspace comparison for team {team} is incomplete (size or count caps hit)"
                    )
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
    store_values = sample.store or {}
    gateway = gateway_index(store_values.get("swarm_bridge_requests") or [], agents_meta)
    joined = store_values.get("swarm_request_actors")
    uid_names = {int(a["uid"]): a["name"] for a in agents_meta if a.get("uid") is not None}
    own, foreign_events, requests, by_order = _split_turns(
        events,
        spans,
        declared,
        _intervals(store_values, events),
        gateway,
        joined if isinstance(joined, dict) else None,
        uid_names,
    )
    gateway_only = _gateway_only_uses(
        gateway,
        requests,
        unjoined_cross_agent_requests(store_values.get("swarm_bridge_requests") or [], agents_meta, joined)
        if isinstance(joined, dict)
        else None,
    )
    uses = bridge_uses(requests) + gateway_only

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

    # No per-call attribution events (a summary-only log): fall back to the
    # end-of-run summary, as unverified claims.
    if not requests:
        uses = _store_summary_uses(_store_value(sample, "swarm_attribution", {})) + gateway_only

    # Connections the watcher saw that no attribution explains: a connection
    # alone, not a confirmed model call.
    bridge_summary = _store_value(sample, "swarm_bridge_summary", {})
    explained = {(u["owner"], u["actor"]) for u in uses}
    for owner, peers in bridge_summary.items():
        for peer in peers:
            if peer != owner and not str(peer).startswith("uid:") and (owner, peer) not in explained:
                uses.append(
                    {
                        "owner": owner,
                        "actor": peer,
                        "kind": "connection",
                        "basis": "watcher",
                        "claimed": None,
                        "mismatch": False,
                        "count": int(peers[peer] or 1),
                    }
                )

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
        requests=requests,
        attribution_by_order=by_order,
        refused_attempts=_refused_attempts(events),
        unidentified_refusals=_gateway_refusals(store_values.get("swarm_bridge_requests") or [], agents_meta),
        agent_stops=_agent_stops(events),
        sample_error=(getattr(sample.error, "message", None) or str(sample.error)) if sample.error else None,
        sample_limit=_sample_limit(sample),
        started_at=next((e.timestamp for e in events if getattr(e, "timestamp", None)), None),
        ended_because=_ended_because(sample, events),
        message_event_ids={
            e.data.get("id"): e.uuid
            for e in events
            if getattr(e, "event", None) == "info"
            and getattr(e, "source", None) == "swarm.message"
            and isinstance(e.data, dict)
            and e.uuid
        },
    )
