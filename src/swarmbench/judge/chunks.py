"""Splitting the compacted ledger into chunks for the chunk review
(docs/judge-two-pass.md, "Chunk review").

Chunks are chronological and cross-agent: consecutive ledger events, whoever
did them, up to a size limit, never splitting an event. Each chunk also shows
context it doesn't own (marked as such): the end of the previous chunk, and
the other end of any recorded link that crosses the boundary (a tool call
whose result lands in the next chunk, a message read much later). Only a
chunk's own events count as read by its review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from swarmbench.judge.compaction import Compacted
from swarmbench.judge.ledger import Ledger

CHUNK_CHARS = 60_000
"""Target size of one chunk's own events (about 15k tokens)."""
OVERLAP_CHARS = 4_000
"""How much of the previous chunk's end is shown as context."""
LINKED_CHARS = 8_000
"""Budget for linked events from outside the chunk."""
LINKED_ITEM_CHARS = 1_500


@dataclass
class Chunk:
    id: str
    events: list[str]
    """Ledger ids this chunk's review is responsible for, in order."""
    context: list[str] = field(default_factory=list)
    """Ledger ids shown for context only (owned by other chunks)."""

    def span(self) -> str:
        return f"{self.events[0]}-{self.events[-1]}" if len(self.events) > 1 else self.events[0]


def make_chunks(ledger: Ledger, view: list[Compacted], max_chars: int = CHUNK_CHARS) -> list[Chunk]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for c in view:
        n = len(c.text)
        if current and size + n > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(c.id)
        size += n
    if current:
        groups.append(current)
    chunks = [Chunk(id=f"C{i + 1:02d}", events=g) for i, g in enumerate(groups)]
    sizes = {c.id: len(c.text) for c in view}
    for i, chunk in enumerate(chunks):
        chunk.context = _context(ledger, chunk.events, chunks[i - 1].events if i else [], sizes)
    return chunks


def split_chunk(ledger: Ledger, view: list[Compacted], chunk: Chunk) -> list[Chunk]:
    """Two halves of a chunk (for a review that was cut off or unreadable)."""
    if len(chunk.events) < 2:
        return [chunk]
    mid = len(chunk.events) // 2
    sizes = {c.id: len(c.text) for c in view}
    first = Chunk(id=f"{chunk.id}.1", events=chunk.events[:mid])
    second = Chunk(id=f"{chunk.id}.2", events=chunk.events[mid:])
    order = {e.id: i for i, e in enumerate(ledger.events)}
    before = [e.id for e in ledger.events if order[e.id] < order[chunk.events[0]]]
    first.context = _context(ledger, first.events, before, sizes)
    second.context = _context(ledger, second.events, first.events, sizes)
    return [first, second]


def _context(ledger: Ledger, own: list[str], previous: list[str], sizes: dict[str, int]) -> list[str]:
    mine = set(own)
    picked: list[str] = []
    budget = OVERLAP_CHARS
    for eid in reversed(previous):
        if sizes.get(eid, 0) > budget:
            break
        picked.insert(0, eid)
        budget -= sizes.get(eid, 0)
    linked_budget = LINKED_CHARS
    seen = set(picked)
    for link in ledger.links:
        for a, b in ((link.src, link.dst), (link.dst, link.src)):
            if a in mine and b not in mine and b not in seen and b.startswith("L"):
                cost = min(sizes.get(b, 0), LINKED_ITEM_CHARS)
                if cost > linked_budget:
                    continue
                picked.append(b)
                seen.add(b)
                linked_budget -= cost
    order = {e.id: i for i, e in enumerate(ledger.events)}
    return sorted(picked, key=lambda x: order.get(x, 0))


def render_chunk(chunk: Chunk, view_by_id: dict[str, Compacted], total_chunks: int) -> str:
    """The chunk as the reviewer reads it: context marked, own events in full."""
    own = set(chunk.events)
    order = {eid: i for i, eid in enumerate(view_by_id)}  # ledger order (ids aren't sortable as text)
    first = order[chunk.events[0]]
    before = [c for c in chunk.context if order.get(c, 0) < first]
    after = [c for c in chunk.context if order.get(c, 0) > first and c not in own]
    parts = [f"<part id=\"{chunk.id}\" of=\"{total_chunks}\" entries=\"{chunk.span()}\">"]
    if before:
        parts.append("<context_before note=\"already reviewed with another part; for context only\">")
        parts += [_clip(view_by_id[c].text) for c in before if c in view_by_id and view_by_id[c].text]
        parts.append("</context_before>")
    parts.append("<entries note=\"review every one of these\">")
    parts += [view_by_id[c].text for c in chunk.events if view_by_id[c].text]  # "" = left out (bookkeeping)
    parts.append("</entries>")
    if after:
        parts.append("<linked_context_after note=\"linked entries from later parts; for context only\">")
        parts += [_clip(view_by_id[c].text) for c in after if c in view_by_id and view_by_id[c].text]
        parts.append("</linked_context_after>")
    parts.append("</part>")
    return "\n\n".join(parts)


def _clip(text: str) -> str:
    return text if len(text) <= LINKED_ITEM_CHARS else text[:LINKED_ITEM_CHARS] + " [...]"
