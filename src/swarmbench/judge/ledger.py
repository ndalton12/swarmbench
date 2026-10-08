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
import json
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


def _call_fingerprint(call: Any) -> str:
    return json.dumps([call.id, call.function, call.arguments or {}], sort_keys=True, default=str)


def _msg_key(m: Any) -> str:
    """A fingerprint of everything the ledger keeps from a message (role, text, reasoning,
    tool calls with their arguments, tool result ids and errors), so a rewritten message
    never passes for re-sent context."""
    err = getattr(m, "error", None)
    raw = json.dumps(
        {
            "role": m.role,
            "text": _msg_text(m),
            "reasoning": _reasoning(m),
            "calls": [_call_fingerprint(c) for c in getattr(m, "tool_calls", None) or []],
            "tool_call_id": getattr(m, "tool_call_id", None),
            "error": getattr(err, "message", None) if err is not None else None,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def call_arguments(text: str) -> dict[str, str]:
    """A tool call's arguments back from its ledger text ("name: value" lines; a value may run
    over several lines)."""
    import re

    args: dict[str, str] = {}
    key = None
    for line in text.split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*): ?(.*)$", line)
        if m and (key is None or m.group(1) not in args):
            key = m.group(1)
            args[key] = m.group(2)
        elif key is not None:
            args[key] += "\n" + line
    return args or {"command": text}


def _tool_ids(m: Any) -> set[str]:
    """Tool-call ids a message carries (its calls, or the call it answers)."""
    out = {c.id for c in getattr(m, "tool_calls", None) or [] if getattr(c, "id", None)}
    if getattr(m, "tool_call_id", None):
        out.add(m.tool_call_id)
    return out


def _same_result(a: str, b: str) -> bool:
    """The same tool result seen twice: only an exact copy. A result that differs anywhere, even
    only in a suffix or by being longer, is kept as its own entry."""
    return a == b


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
        # agent scope -> known conversations: (conversation id, message-key sequence)
        self.conversations: dict[str, list[tuple[str, list[str]]]] = {}
        self.parent: dict[str, str | None] = {}  # conversation -> the one it branched from
        self.inherit: dict[str, set[str]] = {}  # conversation -> tool-call ids in the prefix it shares
        self.msg_ids: dict[str, list[set[str]]] = {}  # conversation -> tool-call ids per message
        self.n_convs = 0
        # tool-call ids are only unique within a conversation: keyed by (conversation id, call id);
        # a branched conversation also sees the ids of the one it branched from
        self.calls: dict[tuple[str, str], tuple[str, str]] = {}  # -> (ledger id, call fingerprint)
        self.results: dict[tuple[str, str | None], tuple[str, str]] = {}  # -> (ledger id, result text)
        self.call_conv: dict[tuple[str, str], str] = {}  # (agent scope, call id) -> latest conversation
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
        # outputs happened when the call finished, not when it was sent: overlapping calls
        # are placed in the order they actually completed
        done = getattr(e, "completed", None) or when
        common = {"owner": owner if foreign else None, "basis": basis if foreign else "",
                  "session": getattr(e, "span_id", None)}
        inputs = list(e.input or [])
        if not inputs and getattr(e, "input_refs", None):
            # Inspect pools repeated inputs in the file and resolves them on read; if a
            # caller ever hands us an unresolved sample, say so instead of losing context
            self.ledger.problems.append(f"model call {e.uuid} has pooled inputs that were not resolved")
        keys = [_msg_key(m) for m in inputs]
        ids = [_tool_ids(m) for m in inputs]
        # which earlier conversation (same agent, any wake session) does this call continue?
        convs = self.conversations.setdefault(scope, [])
        best, best_i = 0, None
        for ci, (_, known) in enumerate(convs):
            n = _common_prefix(known, keys)
            if n > best:
                best, best_i = n, ci
        branched = best_i is not None and best < len(convs[best_i][1])
        if best_i is not None and not branched:
            conv = convs[best_i][0]  # a continuation: the same conversation
        else:
            self.n_convs += 1
            conv = f"{scope}#{self.n_convs}"
            self.parent[conv] = convs[best_i][0] if best_i is not None else None
            if best_i is not None:
                # only what the two share: ids after the split point belong to the parent alone
                shared = self.msg_ids.get(convs[best_i][0], [])[:best]
                self.inherit[conv] = set().union(*shared) if shared else set()
        if branched:
            # a restarted or rewritten conversation: the shared start is the same content as
            # before (not re-added), but the restart itself is an event the judge should see
            dropped = len(convs[best_i][1]) - best
            how = ("started a new conversation that begins the same way as an earlier one"
                   if best == len(inputs) else "continued with a rewritten context")
            self.add(e.uuid, "context", when, "context", None,
                     f"{actor}'s model call {how}: the first {best} messages repeat earlier context; "
                     f"{dropped} later messages of that earlier context are not in this one",
                     agent=actor, reused=best, dropped=dropped, **common)
        for i in range(best, len(inputs)):
            self.input_message(e, i, inputs[i], actor, when, conv, scope, **common)

        out = e.output.message if e.output and e.output.choices else None
        if out is not None:
            for j, r in enumerate(_reasoning(out)):
                self.add(e.uuid, f"reasoning:{j}", done, "reasoning", actor, r, **common)
            text = _msg_text(out)
            if text.strip():
                self.add(e.uuid, "text", done, "text", actor, text, **common)
            for call in out.tool_calls or []:
                self.tool_call(e, call, actor, done, conv, scope, **common)
            keys = keys + [_msg_key(out)]  # the output is context of the next call
            ids = ids + [_tool_ids(out)]
        elif getattr(e, "error", None):
            self.add(e.uuid, "error", done, "error", actor, str(e.error), **common)
        # a continuation replaces the conversation it extends; a branch is kept beside it
        if best_i is not None and not branched:
            convs[best_i] = (conv, keys)
        else:
            convs.append((conv, keys))
        self.msg_ids[conv] = ids
        if not self.ledger.inventory.get(e.uuid):
            self.skip(e.uuid, "model call that only re-sent known context and returned nothing")

    def _find(self, table: dict[Any, Any], conv: str, call_id: str | None) -> Any:
        """A call or result under this id in the conversation, or in the one it branched from when
        the id is in the prefix the two share."""
        seen: str | None = conv
        while seen is not None:
            if (seen, call_id) in table:
                return table[(seen, call_id)]
            if call_id not in self.inherit.get(seen, set()):
                return None
            seen = self.parent.get(seen)
        return None

    def input_message(self, e: Any, i: int, m: Any, actor: str | None, when: Any, conv: str, scope: str,
                      **common: Any) -> None:
        text = _msg_text(m)
        if m.role == "system":
            self.add(e.uuid, f"in:{i}", when, "system", None, text, to=actor, **common)
        elif m.role == "user":
            self.add(e.uuid, f"in:{i}", when, "prompt", None, text, to=actor, **common)
        elif m.role == "tool":
            err = getattr(m, "error", None)
            body = text + (f"\n[error: {err.message}]" if err is not None and getattr(err, "message", None) else "")
            self.tool_result(e.uuid, f"result:{getattr(m, 'tool_call_id', None) or i}", when, actor, body,
                             getattr(m, "tool_call_id", None), getattr(m, "function", None), conv, **common)
        elif m.role == "assistant":
            # an assistant turn that was never a model output here (rewritten history after
            # a compaction, or injected by the scaffold): kept and marked
            for j, r in enumerate(_reasoning(m)):
                self.add(e.uuid, f"in:{i}:reasoning:{j}", when, "reasoning", actor, r, from_input=True, **common)
            if text.strip():
                self.add(e.uuid, f"in:{i}", when, "text", actor, text, from_input=True, **common)
            for call in getattr(m, "tool_calls", None) or []:
                known = self._find(self.calls, conv, call.id)
                if known is None or known[1] != _call_fingerprint(call):
                    self.tool_call(e, call, actor, when, conv, scope, from_input=True, **common)

    def tool_call(self, e: Any, call: Any, actor: str | None, when: Any, conv: str, scope: str,
                  **common: Any) -> None:
        args = "\n".join(f"{k}: {v}" for k, v in (call.arguments or {}).items())
        extra = {}
        known = self._find(self.calls, conv, call.id)
        if known is not None and known[1] != _call_fingerprint(call):
            extra["conflicts_with"] = known[0]  # same id, different call: both kept
        c = self.add(e.uuid, f"call:{call.id}", when, "tool_call", actor, args,
                     function=call.function, tool_call_id=call.id, **extra, **common)
        self.calls[(conv, call.id)] = (c.id, _call_fingerprint(call))
        self.call_conv[(scope, call.id)] = conv

    def tool_result(self, src_uuid: str, part: str, when: Any, actor: str | None, body: str,
                    call_id: str | None, function: str | None, conv: str, **common: Any) -> bool:
        """Add a tool result unless an exact copy (same conversation, id and text) is already in
        the ledger. A different result under a known id is kept and marked as a conflict."""
        extra = {}
        if call_id:
            earlier = self._find(self.results, conv, call_id)
            if earlier is not None:
                if _same_result(earlier[1], body):
                    return False  # the same result, re-sent
                extra["conflicts_with"] = earlier[0]
        r = self.add(src_uuid, part, when, "tool_result", actor, body, tool_call_id=call_id, function=function,
                     **extra, **common)
        if call_id:
            self.results[(conv, call_id)] = (r.id, body)
            call = self._find(self.calls, conv, call_id)
            if call is not None:
                self.ledger.links.append(Link("call_result", call[0], r.id))
        return True

    def tool_event(self, e: Any) -> None:
        # react tools run in Inspect: the result is recorded here (also the last one of a run)
        owner = _owner_of(getattr(e, "span_id", None), self.spans, self.declared)
        body = str(e.result or "") + (f"\n[error: {e.error.message}]" if getattr(e, "error", None) else "")
        when = getattr(e, "completed", None) or e.timestamp
        conv = self.call_conv.get((str(owner), e.id), f"{owner}#tools")
        if not self.tool_result(e.uuid, f"result:{e.id}", when, owner, body, e.id, e.function, conv):
            self.skip(e.uuid, "tool result already in the ledger")

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
        self._order_by_time()
        return self.ledger

    def _order_by_time(self) -> None:
        """Put events in the order they happened (outputs at completion time, so overlapping
        model calls appear in the order they finished), then number them in that order.
        The sort is stable: events with the same time keep log order."""
        events = self.ledger.events
        last = None
        keys = []
        for i, e in enumerate(events):
            last = e.time or last
            keys.append((last.timestamp() if last else 0.0, i))
        order = sorted(range(len(events)), key=lambda i: keys[i])
        renamed = {events[i].id: f"L{n + 1:04d}" for n, i in enumerate(order)}
        self.ledger.events = [events[i] for i in order]
        for e in self.ledger.events:
            e.id = renamed[e.id]
            if "conflicts_with" in e.meta:
                e.meta["conflicts_with"] = renamed.get(e.meta["conflicts_with"], e.meta["conflicts_with"])
        for link in self.ledger.links:
            link.src = renamed.get(link.src, link.src)
            link.dst = renamed.get(link.dst, link.dst)
        for uuid, produced in self.ledger.inventory.items():
            if isinstance(produced, list):
                self.ledger.inventory[uuid] = [renamed[x] for x in produced]


def build_ledger(sample: EvalSample, inputs: SampleInputs) -> Ledger:
    """Build the ledger for one sample (read with attachments resolved)."""
    return _Builder(sample, inputs).build()
