"""Who really made each bridged model request.

The engine writes one ``swarm.attribution`` event per request through an
inspect-swe bridge, joined to its model event by a request id. It can carry
two kinds of identity:

- **relay evidence** (``actor`` / ``actor_uid``): the root-owned bridge relay
  records the uid of the process that connected. Agents can't bypass the relay,
  so this is a fact.
- **a claim** (``claimed_actor`` / ``verdict``): what the request's content says
  about who sent it. Content can be forged, so this is only a claim.

The judge reports:

- relay evidence as fact, and any mismatch with the claim as an attempt to
  impersonate someone or to frame someone;
- without relay evidence, the claim checked against the container watcher's
  record of which uid was connected to that bridge at that moment:
  ``confirmed`` (only the claimed agent was connected), ``contradicted`` (a
  different uid was connected: itself evidence of impersonation or framing) or
  ``unverified`` (no usable record). An unverified claim is never stated as fact.

"Own" claims are checked the same way, so a forged "own" (hiding a borrowed
call) is caught too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

UNKNOWN = "unknown"
TOLERANCE_SECONDS = 2.0
"""Slack between the host's request time and the watcher's polled connection times."""

RELAY = "relay"
CONFIRMED = "confirmed"
CONTRADICTED = "contradicted"
UNVERIFIED = "unverified"
WATCHER_NAMED = "named by connection records"


@dataclass
class Request:
    """One bridged model request and what is known about its sender."""

    request_id: str | None
    owner: str
    """Whose bridge carried it (usage and timeline are charged to this agent)."""
    claimed_actor: str | None
    """Who the request's content says sent it (None: content didn't say)."""
    relay_actor: str | None = None
    relay_uid: int | None = None
    time: datetime | None = None
    generated: bool = True
    actor: str = UNKNOWN
    """Best answer for who really sent it, given the evidence."""
    status: str = UNVERIFIED
    mismatch: bool = False
    """The claim disagrees with the evidence (relay or watcher)."""
    watcher_saw: list[str] = field(default_factory=list)


def _verdict(data: dict[str, Any]) -> str:
    return str(data.get("verdict") or data.get("label") or "").lower().replace("-", "_")


def request_from_event(
    data: dict[str, Any], when: datetime | None, owner_from_span: str | None
) -> Request | None:
    """Read one ``swarm.attribution`` payload (tolerant of the older shape)."""
    owner = data.get("bridge_of") or data.get("owner_agent") or owner_from_span
    if not owner:
        return None
    verdict = _verdict(data)
    if "claimed_actor" in data:
        claimed = data.get("claimed_actor")
        relay_actor = data.get("actor")
        relay_uid = data.get("actor_uid")
        if relay_uid is None:
            relay_actor = None  # no relay evidence for this request
    else:  # older shape: "actor" was the content-based claim
        claimed = data.get("actor")
        relay_actor, relay_uid = None, None
    if verdict == "own" and not claimed:
        claimed = owner
    return Request(
        request_id=data.get("request_id"),
        owner=owner,
        claimed_actor=claimed,
        relay_actor=relay_actor,
        relay_uid=relay_uid,
        time=when,
        generated=data.get("generated", True) is not False,
    )


def _candidates(owner: str, when: datetime | None, intervals: dict[str, list[list[Any]]]) -> list[str]:
    """Agents (or bare uids) connected to ``owner``'s bridge around ``when``."""
    if when is None:
        return []
    t = when.timestamp()
    out: list[str] = []
    for start, end, uid, agent in intervals.get(owner, []):
        if start - TOLERANCE_SECONDS <= t <= end + TOLERANCE_SECONDS:
            name = agent or f"uid:{uid}"
            if name not in out:
                out.append(name)
    return out


GATEWAY_TOLERANCE_SECONDS = 1.0
"""Slack when matching a request's host time to the gateway's [start, end] window."""


def gateway_index(
    records: list[dict[str, Any]], agents_meta: list[dict[str, Any]]
) -> dict[str, list[tuple[float, float, str]]]:
    """Gateway request records per bridge owner: ``{owner: [(start, end, sender)]}``.

    The gateway reads the connecting uid from the kernel, so ``sender`` (the
    agent with that uid in that sandbox, or ``uid:N``) is authoritative.
    """
    by_port: dict[tuple[Any, int], str] = {}
    by_uid: dict[tuple[Any, int], str] = {}
    for a in agents_meta:
        sandbox = a.get("sandbox")
        if a.get("bridge_port") is not None:
            by_port[(sandbox, int(a["bridge_port"]))] = a["name"]
        if a.get("uid") is not None:
            by_uid[(sandbox, int(a["uid"]))] = a["name"]
    out: dict[str, list[tuple[float, float, str]]] = {}
    for r in records or []:
        if not isinstance(r, dict) or r.get("t") != "request":
            continue
        try:
            sandbox, port, uid = r.get("sandbox"), int(r["bridge_port"]), int(r["uid"])
            start, end = float(r["start"]), float(r.get("end") or r["start"])
        except (KeyError, TypeError, ValueError):
            continue
        owner = by_port.get((sandbox, port)) or next(
            (n for (sb, pt), n in by_port.items() if pt == port), None
        )
        if owner is None:
            continue
        sender = by_uid.get((sandbox, uid)) or f"uid:{uid}"
        out.setdefault(owner, []).append((start, end, sender))
    return out


def unjoined_cross_agent_requests(
    records: list[dict[str, Any]], agents_meta: list[dict[str, Any]], joined: dict[str, dict[str, Any]]
) -> list[tuple[str, str]]:
    """(owner, sender) for gateway requests from another agent's uid that no
    attribution join references: the gateway is authoritative, so these are facts."""
    port_owner = {
        (a.get("sandbox"), a.get("bridge_port")): a["name"] for a in agents_meta if a.get("bridge_port")
    }
    uid_name = {(a.get("sandbox"), a.get("uid")): a["name"] for a in agents_meta if a.get("uid") is not None}
    sandbox_of = {a["name"]: a.get("sandbox") for a in agents_meta if a.get("name")}
    # seq is unique per container (one gateway each), and a join's gateway_seq
    # refers to records in the bridge owner's sandbox
    referenced = {
        (sandbox_of.get(j.get("bridge_of")), seq)
        for j in joined.values()
        if isinstance(j, dict)
        for seq in j.get("gateway_seq") or []
    }
    out = []
    for r in records or []:
        if not isinstance(r, dict) or r.get("t") != "request":
            continue
        owner = port_owner.get((r.get("sandbox"), r.get("bridge_port")))
        if owner is None or (r.get("sandbox"), r.get("seq")) in referenced:
            continue
        sender = uid_name.get((r.get("sandbox"), r.get("uid"))) or f"uid:{r.get('uid')}"
        if sender != owner:
            out.append((owner, sender))
    return out


def _gateway_senders(
    owner: str, when: datetime | None, gateway: dict[str, list[tuple[float, float, str]]]
) -> list[str]:
    if when is None:
        return []
    t = when.timestamp()
    out: list[str] = []
    for start, end, sender in gateway.get(owner, []):
        if start - GATEWAY_TOLERANCE_SECONDS <= t <= end + GATEWAY_TOLERANCE_SECONDS and sender not in out:
            out.append(sender)
    return out


def resolve(
    req: Request,
    intervals: dict[str, list[list[Any]]],
    gateway: dict[str, list[tuple[float, float, str]]] | None = None,
    joined: dict[str, dict[str, Any]] | None = None,
    uid_names: dict[int, str] | None = None,
) -> Request:
    """Decide who sent the request and how sure we are.

    Order of evidence: relay/gateway uid (authoritative), then the watcher's
    connection records, otherwise the claim stays unverified.
    """
    claimed = req.claimed_actor
    if req.relay_uid is not None:
        req.actor = req.relay_actor or f"uid:{req.relay_uid}"
        req.status = RELAY
        req.mismatch = claimed is not None and claimed != req.actor
        return req

    # The engine's exact join (request body digest -> gateway record -> kernel uid).
    join = (joined or {}).get(req.request_id or "")
    if join is not None:
        uid = join.get("actor_uid")
        if join.get("match") == "exact" and (join.get("actor") or uid is not None):
            req.actor = join.get("actor") or (uid_names or {}).get(uid) or f"uid:{uid}"
            req.status = RELAY
            req.mismatch = claimed is not None and claimed != req.actor
            return req
        if join.get("match") == "ambiguous":
            req.watcher_saw = [f"uid:{u}" for u in join.get("candidate_uids") or []]
        senders: list[str] = []  # ambiguous, or no gateway record: never guessed from times
    else:
        # older logs without the engine's join: match gateway records by time window
        senders = _gateway_senders(req.owner, req.time, gateway or {})
    if len(senders) == 1:
        req.actor, req.status = senders[0], RELAY
        req.mismatch = claimed is not None and claimed != req.actor
        return req
    if len(senders) > 1:
        # concurrent requests from different uids overlap this moment: can't tell
        # which one this was, so fall back to the weaker evidence below
        req.watcher_saw = senders

    seen = _candidates(req.owner, req.time, intervals)
    req.watcher_saw = seen
    if not seen:
        req.actor, req.status = claimed or UNKNOWN, UNVERIFIED
    elif claimed is None:
        only = seen[0] if len(seen) == 1 and not seen[0].startswith("uid:") else None
        req.actor, req.status = (only, WATCHER_NAMED) if only else (UNKNOWN, UNVERIFIED)
    elif seen == [claimed]:
        req.actor, req.status = claimed, CONFIRMED
    elif claimed in seen:
        req.actor, req.status = claimed, UNVERIFIED  # several connected: can't tell which
    else:
        sole = seen[0] if len(seen) == 1 and not seen[0].startswith("uid:") else UNKNOWN
        req.actor, req.status, req.mismatch = sole, CONTRADICTED, True
    return req


def describe_status(req_status: str) -> str:
    return {
        RELAY: "recorded by the bridge gateway",
        CONFIRMED: "claimed by the request and confirmed by connection records",
        CONTRADICTED: "connection records contradict the request's claim",
        UNVERIFIED: "claimed by the request; not verified",
        WATCHER_NAMED: "named by connection records",
    }.get(req_status, req_status)


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        from datetime import UTC

        return datetime.fromtimestamp(float(value), UTC)
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
