"""Deterministic, reversible compaction of the ledger for the judge to read
(docs/judge-two-pass.md, stage 2 of the design; build stage 1).

- Kept in full: agent reasoning and text, short tool-call arguments, messages
  and board posts, prompts, stops, flags, and anything anomalous.
- Tool outputs over ``LONG_OUTPUT`` characters are cut to head and tail. Lines
  in the cut middle that look like results (exit codes, errors, test
  summaries) are kept, and the event is marked with its id so the full text
  can be fetched (``expand``).
- Long tool-call arguments (scripts written through heredocs) are cut the same
  way, unless the call writes or touches something that matters: a protected
  path, another agent's files or home, a checker or a test, or anything the
  monitor's rules call risky. Those stay whole.
- Bookkeeping is one short line: a wake notice says how many messages and files
  woke the agent; the file-change lines of an activity notice are counted; an
  ordinary attribution record (a call through the agent's own bridge, claiming to
  be its own) is left out of the parts altogether. A mismatched attribution, or a
  call through another agent's bridge, stays in full.
- System prompts and notices are shown once. A later copy says which one it repeats
  ("[system prompt S3, same as before]"); a close variant of an earlier one (the
  same notice preamble, another agent's copy of the same prompt) shows only the
  lines that differ. A changed system prompt for the same agent stays in full.

Nothing here decides what matters: every ledger event is in the compacted view
(an omitted one still counts as read with its part), and every cut is visible
and reversible: the existing tools fetch the full text of any entry.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from swarmbench.judge.framing import as_body, safe_name
from swarmbench.judge.ledger import Ledger, LedgerEvent, call_arguments

LONG_OUTPUT = 2000
HEAD = 800
TAIL = 600
MAX_KEPT_LINES = 12
MAX_KEPT_LINE = 240
REPEAT_MIN = 200
"""Repeated system prompts, notices and tool outputs longer than this point back to the first copy."""
LONG_CALL = 2000
"""Tool-call arguments longer than this are cut to head and tail (unless the call must stay whole)."""
CALL_HEAD = 900
CALL_TAIL = 500
SHORT_LINE = 200
"""Bookkeeping entries up to this long are shown as they are."""
VARIANT_MIN = 300
"""A system text this long that closely matches an earlier one shows only the lines that differ."""
SYSTEM_PROMPT_MIN = 2000
"""A system text this long, for an agent that had a different one with the same opening, is a changed
system prompt: shown in full."""
VERSION = "compaction-2026-10-09"
"""Changes whenever what the judge reads changes (part of the resume key)."""

_RESULT_LINE = re.compile(
    r"(exit (code|status)|returncode|exited with|\berror\b|\bfailed\b|\bfailure\b|traceback|exception|"
    r"\bpassed\b|\bpass\b|\bfail\b|\bok\b|\bdenied\b|not found|\bsuccess|\bwarning\b|\babort|\bkilled\b|"
    r"^\s*(test|result|summary|total)\b)",
    re.IGNORECASE,
)
_FILE_CHANGE_LINE = re.compile(r"^(\S+) changed files in \S+: (.*)$")
_CHECKER_OR_TEST = re.compile(r"check|verif|grader|(^|[_.\-])(tests?|spec)([_.\-]|$)", re.IGNORECASE)
"""A file name that looks like a checker or a test (matched on the name, not the folder)."""
_CODE_SUFFIXES = (".py", ".sh", ".c", ".cc", ".cpp", ".h", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".pl",
                  ".jl", ".r")
"""Scripts an agent writes for itself: a long one may be cut. Any other shared file stays whole."""


@dataclass
class Compacted:
    id: str
    text: str
    """What the judge reads for this event (header line plus body); "" when it is left out of the parts."""
    cut: bool = False
    """True when the body was shortened; ``expand(ledger, id)`` gives the full text."""
    full_chars: int = 0
    shown_chars: int = 0
    why: str = ""
    """How it was shortened (cut, repeat, variant, summary, omitted), for measuring."""


@dataclass
class Policy:
    """What compaction must leave whole: built from the run (``policy_for``)."""

    homes: dict[str, str] = field(default_factory=dict)
    """agent -> home directory."""
    users: dict[str, str] = field(default_factory=dict)
    """linux user -> agent."""
    protected: list[str] = field(default_factory=list)
    """Protected paths (files and read-only folders)."""
    owners: dict[str, str] = field(default_factory=dict)
    """Changed workspace file (relative path) -> its final owner."""

    def keep_call_whole(self, e: LedgerEvent, text: str) -> str:
        """Why a tool call must not be cut ("" when it may be)."""
        from swarmbench.monitor.rules import MAX_SCAN_CHARS, CallContext, call_text, scan_call, write_targets

        args = call_arguments(text)
        fn = e.meta.get("function")
        if len(call_text(args)) > MAX_SCAN_CHARS:  # the rules only read the start: nothing may be cut unseen
            return "too long for the monitor's rules to read in full"
        ctx = CallContext(caller=e.actor, homes=self.homes, users=self.users, protected_paths=self.protected)
        risky = [h for h in scan_call(args, ctx, fn) if h.severity in ("medium", "high", "critical")]
        if risky:
            return f"monitor rule: {risky[0].summary}"
        for t in write_targets(args, fn):
            if any(t == p.rstrip("/") or t.startswith(p.rstrip("/") + "/") for p in self.protected):
                return f"writes the protected path {t}"
            for agent, home in self.homes.items():
                if agent != e.actor and home and (t == home or t.startswith(home.rstrip("/") + "/")):
                    return f"writes {agent}'s files"
            name = t.rsplit("/", 1)[-1]
            if _CHECKER_OR_TEST.search(name):
                return f"writes a checker or test ({t})"
            rel = t.removeprefix("/workspace/").lstrip("./")
            shared = next((p for p in self.owners if rel and (p == rel or p.endswith("/" + rel))), None)
            if shared is None:
                continue
            owner = self.owners[shared]
            if owner and e.actor and owner != e.actor:
                return f"writes {shared}, owned by {owner}"
            if not shared.lower().endswith(_CODE_SUFFIXES):
                # a shared document (a status note, a report, a plan): what it claims matters
                return f"writes the shared file {shared}"
        return ""


def policy_for(inputs: Any, workspace: Any = None) -> Policy:
    """The run's agents, homes, protected paths and file owners."""
    meta = getattr(inputs, "agents_meta", None) or []
    homes = {str(a.get("name")): str(a.get("home")) for a in meta if a.get("name") and a.get("home")}
    users = {str(a.get("user")): str(a.get("name")) for a in meta if a.get("name") and a.get("user")}
    from swarmbench.engine.layout import PROTECTED

    # the protected folder, and each protected file in it (recorded as "team-x:relative/path")
    hashes = getattr(inputs, "protected_hashes", None) or {}
    files = set(hashes.get("before", {})) | set(hashes.get("after", {}))
    protected = [PROTECTED] + sorted(f"{PROTECTED}/{k.split(':', 1)[-1]}" for k in files)
    owners = {f.path: f.owner for f in getattr(workspace, "files", []) or [] if f.owner}
    return Policy(homes=homes, users=users, protected=protected, owners=owners)


def _clock(when: datetime | None, start: datetime | None) -> str:
    if when is None:
        return "--:--:--"
    stamp = when.strftime("%H:%M:%S")
    if start is not None:
        secs = int((when - start).total_seconds())
        stamp += f" +{secs // 60}m{secs % 60:02d}s"
    return stamp


def header(ledger: Ledger, e: LedgerEvent) -> str:
    """The entry's framing line. Names from the record are escaped, so none can break the line."""
    who = safe_name(e.actor) if e.actor else "environment"
    if e.actor is None and e.meta.get("to"):
        who = f"environment to {safe_name(e.meta['to'])}"
    if e.owner and e.owner != e.actor:
        who += f" (via {safe_name(e.owner)}'s bridge, actor {safe_name(e.basis or 'unverified')})"
    what = e.kind
    fn = e.meta.get("function")
    if fn:
        what += f" {safe_name(fn)}"
    if e.meta.get("from_input"):
        what += " (from rewritten context)"
    if e.meta.get("conflicts_with"):
        what += f" (same tool-call id as {e.meta['conflicts_with']} but different content)"
    return f"[{e.id} {_clock(e.time, ledger.started_at)} {who} {what}]"


def _cut(text: str, head: int, tail: int, keep_results: bool) -> str:
    middle = text[head:-tail]
    kept = []
    if keep_results:
        for line in middle.splitlines():
            if _RESULT_LINE.search(line):
                kept.append(line.strip()[:MAX_KEPT_LINE])
                if len(kept) >= MAX_KEPT_LINES:
                    break
    note = f"\n[... {len(middle)} characters cut from the middle"
    note += "; result-like lines from the cut part:]\n" + "\n".join(kept) + "\n[...]\n" if kept else "]\n"
    return text[:head] + note + text[-tail:]


def cut_output(text: str) -> tuple[str, bool]:
    """Head and tail of a long tool output, with result-like middle lines kept."""
    if len(text) <= LONG_OUTPUT:
        return text, False
    return _cut(text, HEAD, TAIL, keep_results=True), True


def cut_call(text: str) -> tuple[str, bool]:
    """Head and tail of a long tool call's arguments (a script written through a heredoc)."""
    if len(text) <= LONG_CALL:
        return text, False
    return _cut(text, CALL_HEAD, CALL_TAIL, keep_results=False), True


def ordinary_attribution(ledger: Ledger, e: LedgerEvent) -> bool:
    """A model call through the agent's own bridge that says it is the agent's own: bookkeeping."""
    text = ledger.text(e)
    return (e.kind == "attribution" and bool(e.actor) and e.actor == e.owner
            and text.endswith(f"content claims own ({e.actor})"))


def _wake_line(e: LedgerEvent, body: str) -> str:
    messages = list(e.meta.get("message_ids") or [])
    files = [str(f) for f in e.meta.get("files") or []]
    bits = []
    if messages:
        shown = ", ".join(str(m) for m in messages[:8]) + (", ..." if len(messages) > 8 else "")
        bits.append(f"{len(messages)} new message(s) ({shown})")
    if files:
        dirs = Counter(f.rsplit("/", 1)[0] for f in files)
        where = ", ".join(f"{d}/ ({n})" for d, n in dirs.most_common(3))
        more = f" and {len(dirs) - 3} more folders" if len(dirs) > 3 else ""
        bits.append(f"{len(files)} changed file(s): {where}{more}")
    what = "; ".join(bits) or "no new messages or files"
    return f"[wake: {e.actor or 'an agent'}, {what}; full text: fetch {e.id}]"


def _activity_notice(e: LedgerEvent, body: str) -> str | None:
    """An activity notice an agent was given: its posts in full, its file-change lines counted."""
    lines = body.split("\n")
    changes = [m for m in (_FILE_CHANGE_LINE.match(ln) for ln in lines) if m]
    if len(changes) < 5:
        return None
    files: dict[str, set[str]] = {}
    for m in changes:
        files.setdefault(m.group(1), set()).update(p.strip() for p in m.group(2).split(","))
    kept = [ln for ln in lines if not _FILE_CHANGE_LINE.match(ln)]
    who = "; ".join(f"{u}: {len(fs)} file(s)" for u, fs in sorted(files.items()))
    summary = (f"[{len(changes)} file-change lines left out ({who}); full text: fetch {e.id}]")
    return "\n".join(kept + [summary])


class _SystemTexts:
    """System prompts and notices: numbered, shown once, close variants as differences."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.number: dict[str, int] = {}  # content key -> S number
        self.first: dict[str, str] = {}  # content key -> first entry id
        self.given: dict[str, set[str]] = {}  # content key -> agents that got it
        self.by_opening: dict[str, list[tuple[str, str, str | None]]] = {}  # first line -> [(id, key, to)]
        self.agent_openings: dict[tuple[str | None, str], set[str]] = {}  # (agent, first line) -> keys

    def render(self, e: LedgerEvent, body: str) -> tuple[str, bool, str]:
        key, to = e.content, e.meta.get("to")
        opening = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")[:200]
        if key in self.number:
            n, first = self.number[key], self.first[key]
            seen_by = self.given.setdefault(key, set())
            self.agent_openings.setdefault((to, opening), set()).add(key)  # variants refer to the first copy
            if len(body) <= SHORT_LINE:
                return body, False, ""
            if to in seen_by:
                return f"[system prompt S{n}, same as before ({first})]", True, "repeat"
            seen_by.add(to)
            return f"[system prompt S{n}, the same text as {first}]", True, "repeat"
        n = self.number[key] = len(self.number) + 1
        self.first[key] = e.id
        self.given.setdefault(key, set()).add(to)
        changed = bool(self.agent_openings.get((to, opening), set()) - {key})
        variant = None
        if len(body) >= VARIANT_MIN and not (changed and len(body) >= SYSTEM_PROMPT_MIN):
            variant = self._variant(body, opening)
        self._note(e, key, to, opening)
        if variant is not None:
            return f"[system prompt S{n}: {variant}", True, "variant"
        label = "changed system prompt" if changed and len(body) >= SYSTEM_PROMPT_MIN else "system prompt"
        return (f"[{label} S{n}]\n" + body) if len(body) > SHORT_LINE else body, False, ""

    def _note(self, e: LedgerEvent, key: str, to: Any, opening: str) -> None:
        self.by_opening.setdefault(opening, []).append((e.id, key, to))
        self.agent_openings.setdefault((to, opening), set()).add(key)

    def _variant(self, body: str, opening: str) -> str | None:
        """Only the lines that differ from the closest earlier text with the same opening, if that is
        much shorter than the text itself."""
        best = None
        for eid, key, _ in reversed(self.by_opening.get(opening, [])[-5:]):
            earlier = self.ledger.store.get(key)
            a, b = earlier.split("\n"), body.split("\n")
            ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            parts = []
            for tag, i1, i2, j1, j2 in ops:  # reversible: the earlier text plus these changes gives this one
                if tag == "equal":
                    continue
                # removed lines are shown too: the change is visible here, without the earlier entry
                theirs = f"line {i1 + 1}" if i2 - i1 == 1 else f"lines {i1 + 1}-{i2}"
                removed = [f"- {ln}" for ln in a[i1:i2]]
                if tag == "delete":
                    parts.append("\n".join([f"@ without {theirs}:", *removed]))
                elif tag == "replace":
                    parts.append("\n".join([f"@ instead of {theirs}:", *removed, *(f"+ {ln}" for ln in b[j1:j2])]))
                else:
                    parts.append("\n".join([f"@ after line {i1}, added:", *(f"+ {ln}" for ln in b[j1:j2])]))
            diff = "\n".join(parts)
            if best is None or len(diff) < len(best[1]):
                best = (eid, diff)
        if best is None or len(best[1]) > len(body) * 0.6:
            return None
        return f"the same as {best[0]} except these lines]\n{best[1]}" if best[1] else f"the same as {best[0]}]"


def compact(ledger: Ledger, policy: Policy | None = None) -> list[Compacted]:
    """Every ledger event, in order, as the judge reads it."""
    policy = policy or Policy()
    first_copy: dict[str, str] = {}  # content key -> first ledger id that showed it
    systems = _SystemTexts(ledger)
    out: list[Compacted] = []
    for e in ledger.events:
        body = ledger.text(e)
        cut, why = False, ""
        if e.kind == "attribution" and ordinary_attribution(ledger, e):
            out.append(Compacted(id=e.id, text="", cut=True, full_chars=len(body), shown_chars=0, why="omitted"))
            continue
        if e.kind == "system":
            shown, cut, why = systems.render(e, body)
        elif (e.kind in ("prompt", "tool_result") and e.content and e.content in first_copy
              and len(body) > REPEAT_MIN):
            shown = f"[identical to the text of {first_copy[e.content]} ({len(body)} characters), shown once]"
            cut, why = True, "repeat"
        elif e.kind == "tool_result":
            shown, cut = cut_output(body)
            if cut:
                shown += f"\n[full output: fetch {e.id}]"
                why = "cut"
        elif e.kind == "tool_call" and len(body) > LONG_CALL and not policy.keep_call_whole(e, body):
            shown, cut = cut_call(body)
            shown += f"\n[full call: fetch {e.id}]"
            why = "cut"
        elif e.kind == "wake" and len(body) > SHORT_LINE:
            shown, cut, why = _wake_line(e, body), True, "summary"
        elif e.kind == "prompt" and len(body) > LONG_OUTPUT and (notice := _activity_notice(e, body)) is not None:
            shown, cut, why = notice, True, "summary"
        else:
            shown = body
        if e.content:
            first_copy.setdefault(e.content, e.id)
        text = header(ledger, e) + ("\n" + as_body(shown) if shown else "")
        out.append(Compacted(id=e.id, text=text, cut=cut, full_chars=len(body), shown_chars=len(shown), why=why))
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
        "omitted_events": sum(1 for c in view if not c.text),
    }
