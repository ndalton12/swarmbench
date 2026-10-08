"""Deterministic, reversible compaction of the ledger for the judge to read
(docs/judge-two-pass.md, stage 2 of the design; build stage 1).

- Kept in full: agent reasoning and text, tool-call arguments, messages and
  board posts, prompts and notices, stops, wakes, flags.
- Tool outputs over ``LONG_OUTPUT`` characters are cut to head and tail. Lines
  in the cut middle that look like results (exit codes, errors, test
  summaries) are kept, and the event is marked with its id so the full text
  can be fetched (``expand``).
- Identical system prompts, notices and tool outputs are shown once; later copies point back
  to the first one.

Nothing here decides what matters: every ledger event appears in the compacted
view, and every cut is visible and reversible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from swarmbench.judge.framing import as_body
from swarmbench.judge.ledger import Ledger, LedgerEvent

LONG_OUTPUT = 2000
HEAD = 800
TAIL = 600
MAX_KEPT_LINES = 12
MAX_KEPT_LINE = 240
REPEAT_MIN = 200
"""Repeated system prompts, notices and tool outputs longer than this point back to the first copy."""

_RESULT_LINE = re.compile(
    r"(exit (code|status)|returncode|exited with|\berror\b|\bfailed\b|\bfailure\b|traceback|exception|"
    r"\bpassed\b|\bpass\b|\bfail\b|\bok\b|\bdenied\b|not found|\bsuccess|\bwarning\b|\babort|\bkilled\b|"
    r"^\s*(test|result|summary|total)\b)",
    re.IGNORECASE,
)


@dataclass
class Compacted:
    id: str
    text: str
    """What the judge reads for this event (header line plus body)."""
    cut: bool = False
    """True when the body was shortened; ``expand(ledger, id)`` gives the full text."""
    full_chars: int = 0
    shown_chars: int = 0


def _clock(when: datetime | None, start: datetime | None) -> str:
    if when is None:
        return "--:--:--"
    stamp = when.strftime("%H:%M:%S")
    if start is not None:
        secs = int((when - start).total_seconds())
        stamp += f" +{secs // 60}m{secs % 60:02d}s"
    return stamp


def header(ledger: Ledger, e: LedgerEvent) -> str:
    who = e.actor or "environment"
    if e.actor is None and e.meta.get("to"):
        who = f"environment to {e.meta['to']}"
    if e.owner and e.owner != e.actor:
        who += f" (via {e.owner}'s bridge, actor {e.basis or 'unverified'})"
    what = e.kind
    fn = e.meta.get("function")
    if fn:
        what += f" {fn}"
    if e.meta.get("from_input"):
        what += " (from rewritten context)"
    if e.meta.get("conflicts_with"):
        what += f" (same tool-call id as {e.meta['conflicts_with']} but different content)"
    return f"[{e.id} {_clock(e.time, ledger.started_at)} {who} {what}]"


def cut_output(text: str) -> tuple[str, bool]:
    """Head and tail of a long tool output, with result-like middle lines kept."""
    if len(text) <= LONG_OUTPUT:
        return text, False
    head, middle, tail = text[:HEAD], text[HEAD:-TAIL], text[-TAIL:]
    kept = []
    for line in middle.splitlines():
        if _RESULT_LINE.search(line):
            kept.append(line.strip()[:MAX_KEPT_LINE])
            if len(kept) >= MAX_KEPT_LINES:
                break
    omitted = len(middle)
    note = f"\n[... {omitted} characters cut from the middle"
    note += "; result-like lines from the cut part:]\n" + "\n".join(kept) + "\n[...]\n" if kept else "]\n"
    return head + note + tail, True


def compact(ledger: Ledger) -> list[Compacted]:
    """Every ledger event, in order, as the judge reads it."""
    first_copy: dict[str, str] = {}  # content key -> first ledger id that showed it
    out: list[Compacted] = []
    for e in ledger.events:
        body = ledger.text(e)
        cut = False
        if (e.kind in ("system", "prompt", "tool_result") and e.content and e.content in first_copy
                and len(body) > REPEAT_MIN):
            shown = f"[identical to the text of {first_copy[e.content]} ({len(body)} characters), shown once]"
            cut = True
        elif e.kind == "tool_result":
            shown, cut = cut_output(body)
            if cut:
                shown += f"\n[full output: fetch {e.id}]"
        else:
            shown = body
        if e.content:
            first_copy.setdefault(e.content, e.id)
        text = header(ledger, e) + ("\n" + as_body(shown) if shown else "")
        out.append(Compacted(id=e.id, text=text, cut=cut, full_chars=len(body), shown_chars=len(shown)))
    return out


def expand(ledger: Ledger, event_id: str) -> str:
    """The full text of one ledger event (reverses any cut)."""
    for e in ledger.events:
        if e.id == event_id:
            return header(ledger, e) + "\n" + as_body(ledger.text(e))
    raise KeyError(event_id)


def stats(ledger: Ledger, view: list[Compacted]) -> dict[str, int]:
    unique = ledger.store.unique_chars()
    shown = sum(len(c.text) for c in view)
    return {
        "events": len(view),
        "unique_chars": unique,
        "compacted_chars": shown,
        "cut_events": sum(1 for c in view if c.cut),
    }
