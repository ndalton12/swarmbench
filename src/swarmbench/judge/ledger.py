"""The event ledger: one immutable, source-addressed record of everything that
happened in a run, for the two-pass judge (docs/judge-two-pass.md, stage 1).

Deterministic, no model calls.

- **Every event, once.** Each agent action and statement (reasoning, text, tool
  calls, tool results, prompts and notices, messages, stops, sleeps and wakes,
  monitor flags) becomes one ledger event with a stable id, a time, a type, and
  the true actor (with the gateway and attribution rules: true actor, bridge
  owner, or unknown). Attachments are resolved by the caller.
- **No deduplication by text.** Repeated actions, compactions and wake sessions
  are kept. Only *re-sent context* is skipped: a model call re-sends its whole
  conversation, so only the messages after the longest known prefix of that
  agent's conversations are new (by position, so a genuine repeat later in the
  conversation is kept; rewritten history after a compaction counts as new).
- **Content stored once.** Identical content (e.g. the same system prompt for
  every agent) is stored once in a content store and referenced.
- **Recorded links.** Tool call -> result, message -> delivery and reads,
  request -> model call. Links a model infers are never mixed in here.
- **Source inventory.** Every Inspect event maps to ledger events or to an
  explicit reason it isn't one, so nothing is left out silently.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from inspect_ai.log import EvalSample

from swarmbench.judge.extract import SampleInputs, _owner_of, _request_id_of, _span_tree, render_message

# Inspect event types that are bookkeeping, never agent behavior.
_STRUCTURAL = {
    "span_begin": "structure (span begin)",
    "span_end": "structure (span end)",
    "sample_init": "bookkeeping (sample start)",
    "state": "bookkeeping (state change)",
    "store": "bookkeeping (store change)",
    "sandbox": "sandbox infrastructure (container exec/read)",
    "logger": "log output",
    "input": "bookkeeping (input)",
    "step": "structure (step)",
    "subtask": "structure (subtask)",
    "score": "scoring",
    "score_edit": "scoring (judge provenance)",
    "sample_limit": "bookkeeping (limit)",
}


@dataclass
class LedgerEvent:
    id: str
    """Short sequential id used in prompts and citations, e.g. ``L0042``."""
    source: str
    """Source address: the Inspect event uuid plus the part, e.g. ``<uuid>#call:toolu_1``."""
    time: datetime | None
    kind: str
    """reasoning | text | tool_call | tool_result | system | prompt | foreign_turn | message |
    read | stop | sleep | wake | run_end | monitor | bridge | attribution | approval | context |
    compaction | encounter | error"""
    actor: str | None
    """Who really did it: an agent, 'unknown', or None for the environment."""
    owner: str | None = None
    """The agent whose span/bridge it landed in, when that differs from the actor."""
    basis: str = ""
    """How the actor was determined for bridged calls (relay, confirmed, unverified, ...)."""
    content: str = ""
    """Key into the content store ("" when there is no text)."""
    session: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Link:
    kind: str
    """call_result | message_delivery | message_read | request"""
    src: str
    dst: str
    meta: dict[str, Any] = field(default_factory=dict)


class ContentStore:
    """Each distinct piece of text stored once, keyed by its hash."""

    def __init__(self) -> None:
        self._text: dict[str, str] = {}
        self.uses: Counter[str] = Counter()

    def put(self, text: str) -> str:
        if not text:
            return ""
        key = hashlib.sha256(text.encode()).hexdigest()[:16]
        self._text.setdefault(key, text)
        self.uses[key] += 1
        return key

    def get(self, key: str) -> str:
        return self._text.get(key, "")

    def unique_chars(self) -> int:
        return sum(len(t) for t in self._text.values())


@dataclass
class Ledger:
    events: list[LedgerEvent] = field(default_factory=list)
    store: ContentStore = field(default_factory=ContentStore)
    links: list[Link] = field(default_factory=list)
    inventory: dict[str, list[str] | str] = field(default_factory=dict)
    """Inspect event uuid -> ledger ids it produced, or the reason it produced none."""
    started_at: datetime | None = None
    problems: list[str] = field(default_factory=list)
    """Things that stop the ledger from being complete (shown as coverage gaps)."""

    def text(self, e: LedgerEvent) -> str:
        return self.store.get(e.content)

    def by_id(self) -> dict[str, LedgerEvent]:
        return {e.id: e for e in self.events}

    def unaccounted(self, sample: EvalSample) -> list[str]:
        """Inspect events that neither produced ledger events nor have a reason."""
        return [e.uuid for e in sample.events or [] if e.uuid and e.uuid not in self.inventory]


def _msg_text(m: Any) -> str:
    content = getattr(m, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if getattr(c, "type", None) == "reasoning":
            continue  # reasoning is its own ledger event
        text = getattr(c, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _reasoning(m: Any) -> list[str]:
    content = getattr(m, "content", "")
    if isinstance(content, str):
        return []
    out = []
    for c in content or []:
        if getattr(c, "type", None) == "reasoning":
            text = getattr(c, "reasoning", None) or getattr(c, "summary", None)
            if text:
                out.append(str(text))
            elif getattr(c, "redacted", False):
                out.append("[reasoning redacted by the provider]")
    return out


def _common_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _msg_key(m: Any) -> str:
    calls = ";".join(f"{c.id}:{c.function}" for c in getattr(m, "tool_calls", None) or [])
    raw = f"{m.role}\x1f{getattr(m, 'tool_call_id', '') or ''}\x1f{calls}\x1f{_msg_text(m)}"
    return hashlib.sha256(raw.encode()).hexdigest()


class _Builder:
    def __init__(self, sample: EvalSample, inputs: SampleInputs) -> None:
        self.sample = sample
        self.inputs = inputs
        self.ledger = Ledger()
        events = sample.events or []
        self.ledger.started_at = next((e.timestamp for e in events if getattr(e, "timestamp", None)), None)
        self.declared = {a.get("name") for a in inputs.agents_meta if a.get("name")} or {a.name for a in inputs.agents}
        self.spans = _span_tree(events)
        self.requests = {r.request_id: r for r in inputs.requests if r.request_id}
        self.conversations: dict[str, list[list[str]]] = {}  # agent -> known message-key sequences
        self.calls: dict[str, str] = {}  # tool_call_id -> ledger id of the call
        self.results: set[str] = set()  # tool_call_ids with a result already in the ledger
        self.messages: dict[Any, str] = {}  # swarm message id -> ledger id
        self.attributions: dict[str, str] = {}  # request id -> ledger id

    # -- helpers ---------------------------------------------------------------

    def add(self, src_uuid: str, part: str, when: Any, kind: str, actor: str | None, text: str = "",
            **extra: Any) -> LedgerEvent:
        e = LedgerEvent(
            id=f"L{len(self.ledger.events) + 1:04d}",
            source=f"{src_uuid}#{part}",
            time=when,
            kind=kind,
            actor=actor,
            content=self.ledger.store.put(text),
            owner=extra.pop("owner", None),
            basis=extra.pop("basis", ""),
            session=extra.pop("session", None),
            meta=extra,
        )
        self.ledger.events.append(e)
        produced = self.ledger.inventory.setdefault(src_uuid, [])
        if isinstance(produced, list):
            produced.append(e.id)
        return e

    def skip(self, src_uuid: str, reason: str) -> None:
        if src_uuid and src_uuid not in self.ledger.inventory:
            self.ledger.inventory[src_uuid] = reason

    # -- model calls --------------------------------------------------------------

    def model_event(self, e: Any) -> None:
        owner = _owner_of(getattr(e, "span_id", None), self.spans, self.declared)
        req = self.requests.get(_request_id_of(e) or "")
        actor, basis = owner, "own"
        if req is not None and req.actor != owner:
            actor, basis = req.actor, req.status
        foreign = actor != owner
        scope = f"{owner}" + (f"|via:{actor}" if foreign else "")
        when = e.timestamp
        common = {"owner": owner if foreign else None, "basis": basis if foreign else "",
                  "session": getattr(e, "span_id", None)}
        inputs = list(e.input or [])
        if not inputs and getattr(e, "input_refs", None):
            # Inspect pools repeated inputs in the file and resolves them on read; if a
            # caller ever hands us an unresolved sample, say so instead of losing context
            self.ledger.problems.append(f"model call {e.uuid} has pooled inputs that were not resolved")
        keys = [_msg_key(m) for m in inputs]
        # which earlier conversation (same agent, any wake session) does this call continue?
        convs = self.conversations.setdefault(scope, [])
        best, best_i = 0, None
        for ci, known in enumerate(convs):
            n = _common_prefix(known, keys)
            if n > best:
                best, best_i = n, ci
        branched = best_i is not None and best < len(convs[best_i])
        if branched:
            # a restarted or rewritten conversation: the shared start is the same content as
            # before (not re-added), but the restart itself is an event the judge should see
            dropped = len(convs[best_i]) - best
            how = ("started a new conversation that begins the same way as an earlier one"
                   if best == len(inputs) else "continued with a rewritten context")
            self.add(e.uuid, "context", when, "context", None,
                     f"{actor}'s model call {how}: the first {best} messages repeat earlier context; "
                     f"{dropped} later messages of that earlier context are not in this one",
                     agent=actor, reused=best, dropped=dropped, **common)
        for i in range(best, len(inputs)):
            self.input_message(e, i, inputs[i], actor, when, **common)

        out = e.output.message if e.output and e.output.choices else None
        if out is not None:
            for j, r in enumerate(_reasoning(out)):
                self.add(e.uuid, f"reasoning:{j}", when, "reasoning", actor, r, **common)
            text = _msg_text(out)
            if text.strip():
                self.add(e.uuid, "text", when, "text", actor, text, **common)
            for call in out.tool_calls or []:
                self.tool_call(e, call, actor, when, **common)
            keys = keys + [_msg_key(out)]  # the output is context of the next call
        elif getattr(e, "error", None):
            self.add(e.uuid, "error", when, "error", actor, str(e.error), **common)
        # a continuation replaces the conversation it extends; a branch is kept beside it
        if best_i is not None and not branched:
            convs[best_i] = keys
        else:
            convs.append(keys)
        if not self.ledger.inventory.get(e.uuid):
            self.skip(e.uuid, "model call that only re-sent known context and returned nothing")

    def input_message(self, e: Any, i: int, m: Any, actor: str | None, when: Any, **common: Any) -> None:
        text = _msg_text(m)
        if m.role == "system":
            self.add(e.uuid, f"in:{i}", when, "system", None, text, to=actor, **common)
        elif m.role == "user":
            self.add(e.uuid, f"in:{i}", when, "prompt", None, text, to=actor, **common)
        elif m.role == "tool":
            call_id = getattr(m, "tool_call_id", None)
            if call_id and call_id in self.results:
                return  # the same result re-sent in a branched conversation
            err = getattr(m, "error", None)
            body = text + (f"\n[error: {err.message}]" if err is not None and getattr(err, "message", None) else "")
            r = self.add(e.uuid, f"result:{call_id or i}", when, "tool_result", actor, body,
                         tool_call_id=call_id, function=getattr(m, "function", None), **common)
            if call_id:
                self.results.add(call_id)
                if call_id in self.calls:
                    self.ledger.links.append(Link("call_result", self.calls[call_id], r.id))
        elif m.role == "assistant":
            # an assistant turn that was never a model output here (rewritten history after
            # a compaction, or injected by the scaffold): kept and marked
            for j, r in enumerate(_reasoning(m)):
                self.add(e.uuid, f"in:{i}:reasoning:{j}", when, "reasoning", actor, r, from_input=True, **common)
            if text.strip():
                self.add(e.uuid, f"in:{i}", when, "text", actor, text, from_input=True, **common)
            for call in getattr(m, "tool_calls", None) or []:
                if call.id not in self.calls:
                    self.tool_call(e, call, actor, when, from_input=True, **common)

    def tool_call(self, e: Any, call: Any, actor: str | None, when: Any, **common: Any) -> None:
        args = "\n".join(f"{k}: {v}" for k, v in (call.arguments or {}).items())
        c = self.add(e.uuid, f"call:{call.id}", when, "tool_call", actor, args,
                     function=call.function, tool_call_id=call.id, **common)
        self.calls[call.id] = c.id

    def tool_event(self, e: Any) -> None:
        # react tools run in Inspect: the result is recorded here (also the last one of a run)
        owner = _owner_of(getattr(e, "span_id", None), self.spans, self.declared)
        if e.id in self.results:
            self.skip(e.uuid, "tool result already in the ledger")
            return
        body = str(e.result or "") + (f"\n[error: {e.error.message}]" if getattr(e, "error", None) else "")
        r = self.add(e.uuid, f"result:{e.id}", e.timestamp, "tool_result", owner, body,
                     tool_call_id=e.id, function=e.function)
        self.results.add(e.id)
        if e.id in self.calls:
            self.ledger.links.append(Link("call_result", self.calls[e.id], r.id))

    # -- swarm events ----------------------------------------------------------------

    def info_event(self, e: Any) -> None:
        source = getattr(e, "source", "") or ""
        data = e.data if isinstance(e.data, dict) else {}
        when = e.timestamp
        if source == "swarm.message":
            m = self.add(e.uuid, "message", when, "message", data.get("sender"), render_message(data),
                         message_id=data.get("id"), to=data.get("to"), channel=data.get("channel"),
                         claimed_sender=data.get("claimed_sender"), via_bridge_of=data.get("via_bridge_of"))
            self.messages[data.get("id")] = m.id
            for recipient in data.get("delivered_to") or []:
                self.ledger.links.append(Link("message_delivery", m.id, str(recipient)))
        elif source == "swarm.read":
            r = self.add(e.uuid, "read", when, "read", data.get("agent"),
                         f"{data.get('agent')} was shown messages {data.get('ids')}", ids=data.get("ids"))
            for mid in data.get("ids") or []:
                if mid in self.messages:
                    self.ledger.links.append(Link("message_read", self.messages[mid], r.id))
        elif source == "swarm.agent_stopped":
            self.add(e.uuid, "stop", when, "stop", data.get("agent"),
                     f"{data.get('agent')} stopped ({data.get('reason')})", reason=data.get("reason"))
        elif source == "swarm.agent_sleep":
            self.add(e.uuid, "sleep", when, "sleep", data.get("agent"), f"{data.get('agent')} went idle")
        elif source == "swarm.agent_wake":
            self.add(e.uuid, "wake", when, "wake", data.get("agent"),
                     f"{data.get('agent')} was woken (messages {data.get('message_ids') or []}, "
                     f"files {data.get('files') or []})", message_ids=data.get("message_ids"),
                     files=data.get("files"))
        elif source == "swarm.run_end":
            self.add(e.uuid, "run_end", when, "run_end", None, f"run ended: {data.get('reason')}")
        elif source == "swarm.monitor":
            self.add(e.uuid, "monitor", when, "monitor", data.get("agent"),
                     f"monitor ({data.get('severity')}, {data.get('category')}, {data.get('action')}): "
                     f"{data.get('summary')} | {data.get('evidence', '')}", **{k: data.get(k) for k in
                                                                              ("severity", "category", "action")})
        elif source == "swarm.bridge":
            self.add(e.uuid, "bridge", when, "bridge", data.get("peer_agent") or f"uid:{data.get('peer_uid')}",
                     f"connection to {data.get('owner_agent')}'s bridge from "
                     f"{data.get('peer_agent') or 'uid ' + str(data.get('peer_uid'))}", owner=data.get("owner_agent"))
        elif source == "swarm.attribution":
            a = self.add(e.uuid, "attribution", when, "attribution", data.get("claimed_actor"),
                         f"request {data.get('request_id')} on {data.get('bridge_of')}'s bridge: content claims "
                         f"{data.get('verdict')} ({data.get('claimed_actor')})", owner=data.get("bridge_of"),
                         request_id=data.get("request_id"), generated=data.get("generated", True))
            if data.get("request_id"):
                self.attributions[str(data["request_id"])] = a.id
        elif source == "swarm.encounter":
            self.add(e.uuid, "encounter", when, "encounter", None,
                     f"a shared channel opened ({data.get('via')}, {data.get('path')})")
        else:
            self.add(e.uuid, "info", when, "info", None, f"{source}: {data}"[:2000], source=source)

    def approval_event(self, e: Any) -> None:
        decision = getattr(e, "decision", None)
        if decision in ("approve", None):
            self.skip(e.uuid, "approved tool call (the call itself is in the ledger)")
            return
        call = getattr(e, "call", None)
        owner = _owner_of(getattr(e, "span_id", None), self.spans, self.declared)
        self.add(e.uuid, "approval", e.timestamp, "approval", owner,
                 f"tool call {getattr(call, 'function', '?')} {decision}: {getattr(e, 'explanation', '')}",
                 decision=decision)

    def build(self) -> Ledger:
        for e in self.sample.events or []:
            kind = getattr(e, "event", None)
            if kind == "model":
                self.model_event(e)
            elif kind == "tool":
                self.tool_event(e)
            elif kind == "info":
                self.info_event(e)
            elif kind == "approval":
                self.approval_event(e)
            elif kind == "compaction":
                owner = _owner_of(getattr(e, "span_id", None), self.spans, self.declared)
                self.add(e.uuid, "compaction", e.timestamp, "compaction", owner,
                         f"{owner}'s context was compacted ({getattr(e, 'tokens_before', '?')} -> "
                         f"{getattr(e, 'tokens_after', '?')} tokens)")
            elif kind == "error":
                self.add(e.uuid, "error", e.timestamp, "error", None, str(getattr(e, "error", "")))
            elif kind in _STRUCTURAL:
                self.skip(e.uuid, _STRUCTURAL[kind])
            else:
                self.skip(e.uuid, f"not agent behavior ({kind})")
        # request id -> the model call it attributes
        for e in self.sample.events or []:
            if getattr(e, "event", None) == "model":
                rid = _request_id_of(e)
                produced = self.ledger.inventory.get(e.uuid)
                if rid and rid in self.attributions and isinstance(produced, list) and produced:
                    self.ledger.links.append(Link("request", self.attributions[rid], produced[0]))
        return self.ledger


def build_ledger(sample: EvalSample, inputs: SampleInputs) -> Ledger:
    """Build the ledger for one sample (read with attachments resolved)."""
    return _Builder(sample, inputs).build()
