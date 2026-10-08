"""The coverage manifest: which ledger events each successful judge call read,
and with which model, reconciled against the source inventory
(docs/judge-two-pass.md, build stage 1).

Coverage is a recorded fact, never an inference from a verdict: "every event
was read" comes from this manifest; "nothing concerning happened" comes from
the judge's findings. A read only counts when its call succeeded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from inspect_ai.log import EvalSample

from swarmbench.judge.ledger import Ledger


@dataclass
class Read:
    call: str
    """The judge call's id (e.g. ``chunk-03`` or ``reconcile``)."""
    model: str
    events: list[str]
    ok: bool = True
    note: str = ""


@dataclass
class Manifest:
    ledger: Ledger
    reads: list[Read] = field(default_factory=list)

    def record(self, call: str, model: str, events: list[str], ok: bool = True, note: str = "") -> None:
        self.reads.append(Read(call=call, model=model, events=list(events), ok=ok, note=note))

    def read_by(self) -> dict[str, set[str]]:
        """Ledger id -> models whose successful calls read it."""
        out: dict[str, set[str]] = {}
        for r in self.reads:
            if r.ok:
                for eid in r.events:
                    out.setdefault(eid, set()).add(r.model)
        return out

    def unread(self) -> list[str]:
        read = self.read_by()
        return [e.id for e in self.ledger.events if e.id not in read]

    def spans_by_model(self) -> dict[str, list[str]]:
        """Each model's successfully read events as compact ranges (``L0001-L0040``)."""
        order = {e.id: i for i, e in enumerate(self.ledger.events)}
        per: dict[str, set[str]] = {}
        for eid, models in self.read_by().items():
            for m in models:
                per.setdefault(m, set()).add(eid)
        return {m: ranges(sorted(ids, key=lambda x: order.get(x, 0)), order) for m, ids in sorted(per.items())}

    def reconcile(self, sample: EvalSample) -> list[str]:
        """Plain-language coverage problems; empty means complete coverage."""
        problems = list(self.ledger.problems)
        unaccounted = self.ledger.unaccounted(sample)
        if unaccounted:
            problems.append(f"{len(unaccounted)} log events were neither put in the ledger nor explained")
        unread = self.unread()
        if unread:
            order = {e.id: i for i, e in enumerate(self.ledger.events)}
            problems.append(
                f"{len(unread)} of {len(self.ledger.events)} ledger events were not read by any successful "
                f"judge call ({', '.join(ranges(unread, order)[:8])})"
            )
        read = self.read_by()
        for r in self.reads:
            # a failed call matters only if a later retry or split didn't read its events
            if not r.ok and any(eid not in read for eid in r.events):
                problems.append(f"judge call {r.call} ({r.model}) failed" + (f": {r.note}" if r.note else ""))
        return problems

    def to_json(self) -> dict[str, Any]:
        excluded: dict[str, int] = {}
        for value in self.ledger.inventory.values():
            if isinstance(value, str):
                excluded[value] = excluded.get(value, 0) + 1
        return {
            "ledger_events": len(self.ledger.events),
            "source_events_mapped": sum(1 for v in self.ledger.inventory.values() if isinstance(v, list)),
            "source_events_excluded": excluded,
            "read_by_model": self.spans_by_model(),
            "unread": self.unread(),
            "calls": [
                {"call": r.call, "model": r.model, "events": len(r.events), "ok": r.ok, "note": r.note}
                for r in self.reads
            ],
        }


def ranges(ids: list[str], order: dict[str, int]) -> list[str]:
    """Consecutive ledger ids collapsed to ``first-last`` ranges."""
    out: list[str] = []
    start = prev = None
    for eid in ids:
        if start is None:
            start = prev = eid
            continue
        if order.get(eid, -2) == order.get(prev, -5) + 1:
            prev = eid
            continue
        out.append(start if start == prev else f"{start}-{prev}")
        start = prev = eid
    if start is not None:
        out.append(start if start == prev else f"{start}-{prev}")
    return out
