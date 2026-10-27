"""Rebuilding an agent's next model request with one tool result swapped (the agent-reaction test).

Used by ``reaction.py`` (read that module's docstring first). This module does three things:

1. **Reads only what it needs from a run log**, one log at a time. A run's Inspect log is one sample
   whose JSON can be 500 MB, so it is streamed (``ijson``) instead of loaded: the model events asked
   for, the pooled input messages they point at, and the attachments those reference. Nothing else is
   kept. A light record of every model event (id, span, time, which pooled messages its input uses)
   is kept too, to check which call first carried a result.

2. **Finds the agent's next model call** after a tool call and the tool result in it. The commands
   table already names it (``result_event``: the model call whose input first carried the result,
   found by the judge's event ledger, which attributes every model call to its agent by the agent's
   span and, for a call made through another agent's bridge, by the gateway's request record). Here
   it is checked again from the log itself, without the ledger:

   - the target result is found in that call's input: a tool message answering the call's id, or,
     when the harness renamed the ids (Antigravity), the tool message whose text, read the way the
     commands table reads it, equals the recorded output; for an Antigravity background task, the
     ``<SYSTEM_MESSAGE>`` notice "Task id X finished" inside a later message;
   - Inspect stores each distinct message once in a pool and each model call's input as ranges of
     pool positions, so "carries this result" means "its ranges cover the result's pool position".
     The first model event (by time) whose input covers it must be the named call, and its span must
     belong to the same agent (the outermost agent span, as the judge reads spans).

3. **Swaps the tool result's payload** (``swap_payload``) and nothing else: the harness's wrapper
   stays, as do its exit-code line (set to the predicted exit code when the harness shows one), the
   notices it appends (``<system-reminder>`` blocks, other tasks' ``<SYSTEM_MESSAGE>`` notices) and
   other results of the same turn. Per harness:

   - **Claude Code**: the content is the output, starting with ``Exit code N`` when the command
     failed, then any ``<system-reminder>`` blocks; a failed command also carries the same text as
     the message's error. The predicted payload goes in its place; the ``Exit code`` line and the
     error are set from the predicted exit code (none for 0).
   - **Codex**: the content is a header part ("Script completed / Wall time / Output:") and one part
     per printed chunk, either plain text or a JSON object whose ``output`` holds the text and whose
     ``exit_code`` the exit code. The predicted payload goes into the single chunk (JSON fields other
     than ``output`` and ``exit_code`` are kept). A result with several chunks is swapped only when
     the prediction has the same number of chunks; otherwise the case is not built. The header (its
     wall time included) is kept: the test changes what the command printed, not how long it took.
   - **Antigravity**: the content is JSON ``{"output": ...}`` whose text starts with a status line
     ("The command completed successfully." or "The command failed with exit code: N") and an
     ``Output:`` label; the status line follows the predicted exit code, the payload goes after the
     label, and anything after the payload (other tasks' notices) is kept. A background task's
     result is the body of its finish notice; only that body is swapped.

   The prediction is stripped of any wrapper the auditor copied from the history (it was shown
   outputs with their wrappers) before it is put in, so it never ends up wrapped twice.

Swapping the real payload back in must give the logged message byte for byte; ``reaction.py`` checks
this for every case (and, for small logs, against Inspect's own reader too).
"""

from __future__ import annotations

import copy
import json
import math
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ATTACHMENT = "attachment://"


# --- reading a log ---------------------------------------------------------------------------------------


def _zip(log_path: Path) -> tuple[zipfile.ZipFile, str]:
    # Inspect writes zstd-compressed entries, in several frames when large; importing its helper teaches
    # zipfile to read both
    import inspect_ai._util.zipfile  # noqa: F401

    z = zipfile.ZipFile(log_path)
    names = [n for n in z.namelist() if n.startswith("samples/") and n.endswith(".json")]
    if len(names) != 1:
        z.close()
        raise ValueError(f"{log_path}: expected one sample, found {len(names)}")
    return z, names[0]


def _items(log_path: Path, prefix: str) -> Iterator[Any]:
    import ijson

    z, name = _zip(log_path)
    try:
        with z.open(name) as f:
            yield from ijson.items(f, prefix, use_float=True)
    finally:
        z.close()


def _kvitems(log_path: Path, prefix: str) -> Iterator[tuple[str, Any]]:
    import ijson

    z, name = _zip(log_path)
    try:
        with z.open(name) as f:
            yield from ijson.kvitems(f, prefix, use_float=True)
    finally:
        z.close()


@dataclass
class ModelMeta:
    """What is kept of every model event: enough to say which one first carried a message."""

    uuid: str
    span_id: str | None
    timestamp: str
    model: str
    refs: list[tuple[int, int]]

    def covers(self, pool_index: int) -> bool:
        return any(a <= pool_index < b for a, b in self.refs)


@dataclass
class LogSlice:
    """The parts of one run log the reaction test needs."""

    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Wanted model events by uuid, raw JSON with ``input`` filled in and attachments resolved."""
    meta: list[ModelMeta] = field(default_factory=list)
    spans: dict[str, tuple[str, str | None, str | None]] = field(default_factory=dict)
    agents: list[str] = field(default_factory=list)
    pool_index: dict[str, list[int]] = field(default_factory=dict)
    """uuid -> the pool position of each of its input messages (same order as ``input``)."""


def _expand(refs: list[Any]) -> list[int]:
    out: list[int] = []
    for a, b in refs or []:
        out.extend(range(int(a), int(b)))
    return out


def _attachment_refs(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        if value.startswith(ATTACHMENT):
            out.add(value[len(ATTACHMENT):])
    elif isinstance(value, dict):
        for v in value.values():
            _attachment_refs(v, out)
    elif isinstance(value, list):
        for v in value:
            _attachment_refs(v, out)


def resolve_attachments(value: Any, attachments: dict[str, str]) -> Any:
    """Replace every ``attachment://<hash>`` string with its text, as Inspect does on read (a reference
    whose text is missing is left as it is)."""
    if isinstance(value, str):
        if value.startswith(ATTACHMENT):
            return attachments.get(value[len(ATTACHMENT):], value)
        return value
    if isinstance(value, dict):
        return {k: resolve_attachments(v, attachments) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_attachments(v, attachments) for v in value]
    return value


def read_log_slice(log_path: Path, want: Iterable[str]) -> LogSlice:
    """Stream one log: the wanted model events (inputs rebuilt from the message pool, attachments
    resolved), plus a light record of every model event and every span."""
    want = set(want)
    out = LogSlice()
    meta = next(_items(log_path, "metadata"), None) or {}
    out.agents = [a.get("name") for a in ((meta.get("swarm") or {}).get("agents") or []) if a.get("name")]
    for e in _items(log_path, "events.item"):
        kind = e.get("event")
        if kind == "span_begin":
            out.spans[e.get("id")] = (e.get("name"), e.get("type"), e.get("parent_id"))
        elif kind == "model":
            refs = [(int(a), int(b)) for a, b in (e.get("input_refs") or [])]
            out.meta.append(ModelMeta(e.get("uuid"), e.get("span_id"), e.get("timestamp") or "", e.get("model") or "",
                                      refs))
            if e.get("uuid") in want:
                out.events[e["uuid"]] = e
    # pooled input messages, only the positions the wanted events use
    needed: set[int] = set()
    for e in out.events.values():
        if e.get("input_refs"):
            positions = _expand(e["input_refs"])
            out.pool_index[e["uuid"]] = positions
            needed.update(positions)
    pool: dict[int, Any] = {}
    if needed:
        for i, m in enumerate(_items(log_path, "events_data.messages.item")):
            if i in needed:
                pool[i] = m
                if len(pool) == len(needed):
                    break
    for uuid, e in out.events.items():
        if e.get("input_refs"):
            e["input"] = [pool[i] for i in out.pool_index[uuid]]
            e["input_refs"] = None
        else:
            out.pool_index[uuid] = []
    # attachments, only those referenced
    hashes: set[str] = set()
    for e in out.events.values():
        _attachment_refs({k: e.get(k) for k in ("input", "tools", "tool_choice", "config", "output")}, hashes)
    attachments: dict[str, str] = {}
    if hashes:
        for k, v in _kvitems(log_path, "attachments"):
            if k in hashes:
                attachments[k] = v
                if len(attachments) == len(hashes):
                    break
    for uuid, e in list(out.events.items()):
        for k in ("input", "tools", "tool_choice", "config", "output"):
            if k in e:
                e[k] = resolve_attachments(e[k], attachments)
    return out


def owner_of(span_id: str | None, spans: dict[str, tuple[str, str | None, str | None]], declared: set[str]) -> str | None:
    """The outermost declared agent span containing a span (the judge's rule, ``judge.extract._owner_of``)."""
    from swarmbench.judge.extract import _owner_of

    return _owner_of(span_id, spans, declared)


# --- message text, as the commands table reads it ----------------------------------------------------------


def message_text(m: dict[str, Any]) -> str:
    """A raw message's text as the judge's ledger reads it (text parts joined by newlines, reasoning
    left out), plus the ``[error: ...]`` line the ledger adds for a tool error."""
    content = m.get("content")
    if isinstance(content, str):
        text = content
    else:
        parts = []
        for c in content or []:
            if isinstance(c, dict) and c.get("type") != "reasoning" and c.get("text"):
                parts.append(str(c["text"]))
        text = "\n".join(parts)
    err = m.get("error")
    if m.get("role") == "tool" and isinstance(err, dict) and err.get("message"):
        text += f"\n[error: {err['message']}]"
    return text


def recorded_output(harness: str, text: str) -> str:
    """What the commands table records as a (foreground) tool result's output, from the ledger text."""
    from swarmbench.studies.auditor.extract import split_system_messages, strip_reminders, unwrap_envelope

    if harness == "antigravity":
        return split_system_messages(unwrap_envelope(text))[0]
    if harness == "claude_code":
        return strip_reminders(text)
    return text


# --- splitting a tool result into wrapper and payload, per harness -------------------------------------------


class Unbuildable(ValueError):
    """A case whose input can't be rebuilt faithfully (the message says why)."""


@dataclass
class Parts:
    """A tool result's text seen as a wrapper around a payload."""

    form: str
    """The wrapper: "plain", "exit_line" (Claude Code's shell), "ag_output", "ag_split", "ag_message"."""
    payload: str
    exit_code: int | None
    """The exit code the wrapper shows (None when it shows none)."""
    lead: str = ""
    mid: str = ""
    tail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# Claude Code ---------------------------------------------------------------------------------------------

_CC_EXIT_LINE = re.compile(r"\AExit code (-?\d+)(?:\n|\Z)")
_CC_REMINDERS = re.compile(r"(?:\s*<system-reminder>.*?</system-reminder>)+\s*\Z", re.DOTALL)
_CC_HARNESS_MESSAGE = re.compile(r"\A\s*(?:Command timed out|Error:|<tool_use_error>|\[Request interrupted)")
_CC_ERROR_SUFFIX = re.compile(r"\n\[error: .*\]\s*\Z", re.DOTALL)


def split_cc(text: str, function: str) -> Parts:
    """Claude Code: ``Exit code N`` first when a shell command failed, then the output, then any
    ``<system-reminder>`` blocks the harness appended."""
    m = _CC_REMINDERS.search(text)
    tail = text[m.start():] if m else ""
    body = text[: len(text) - len(tail)]
    if "<system-reminder>" in body:
        raise Unbuildable("Claude Code result with a <system-reminder> inside the output")
    if function in ("Bash", "bash"):
        e = _CC_EXIT_LINE.match(body)
        if e:
            return Parts("exit_line", body[e.end():], int(e.group(1)), tail=tail)
        return Parts("exit_line", body, None if _CC_HARNESS_MESSAGE.match(body) else 0, tail=tail)
    return Parts("plain", body, None, tail=tail)


def render_cc(p: Parts, payload: str, exit_code: int | None) -> str:
    if p.form == "exit_line" and exit_code not in (None, 0):
        return f"Exit code {exit_code}\n{payload}{p.tail}" if payload else f"Exit code {exit_code}{p.tail}"
    return f"{payload}{p.tail}"


# Antigravity ---------------------------------------------------------------------------------------------

_AG_STATUS = r"(?P<status>The command completed successfully\.|The command failed with exit code: (?P<code>-?\d+))"
_AG_OUTPUT = re.compile(r"\A(?P<lead>\s*)" + _AG_STATUS + r"(?P<mid>\n\t*Output:\n\t*)(?P<payload>.*)\Z", re.DOTALL)
_AG_SPLIT = re.compile(r"\A(?P<lead>\s*)" + _AG_STATUS + r"(?P<mid>\n\t*Stdout:\n\t*)(?P<stdout>.*?)"
                       r"(?P<mid2>\n\t*Stderr:\n\t*)(?P<stderr>.*?)(?P<end>\n?)\Z", re.DOTALL)
AG_LEAD = "\n\t\t\t\t"
AG_OUTPUT_MID = "\n\t\t\t\tOutput:\n\t\t\t\t"
AG_SPLIT_MID = "\n\t\t\t\tStdout:\n\t\t\t\t"
AG_SPLIT_MID2 = "\n\t\t\t\tStderr:\n\t\t\t\t"
_AG_HARNESS_MESSAGE = re.compile(r"\A\s*(?:Encountered error in step execution|Tool is running as a background task)")


def _ag_status(code: int) -> str:
    return "The command completed successfully." if code == 0 else f"The command failed with exit code: {code}"


def split_ag(own: str) -> Parts:
    """Antigravity's run_command text (inside its JSON envelope, other tasks' notices cut off): a status
    line, then ``Output:`` and the output, or (for an empty output) empty ``Stdout:`` and ``Stderr:``
    sections; or one of the harness's own messages (a time-out), with no payload slot."""
    m = _AG_OUTPUT.match(own)
    if m:
        return Parts("ag_output", m.group("payload"), int(m.group("code") or 0), lead=m.group("lead"),
                     mid=m.group("mid"))
    m = _AG_SPLIT.match(own)
    if m:
        return Parts("ag_split", m.group("stdout") + m.group("stderr"), int(m.group("code") or 0),
                     lead=m.group("lead"), mid=m.group("mid"),
                     extra={"mid2": m.group("mid2"), "end": m.group("end"), "stdout": m.group("stdout"),
                            "stderr": m.group("stderr")})
    return Parts("ag_message", own, None)


def render_ag(p: Parts, payload: str, exit_code: int | None, *, is_message: bool = False,
              default_lead: str = AG_LEAD) -> str:
    """Antigravity shows an empty output as empty Stdout/Stderr sections and anything else after an
    ``Output:`` label (in the logs the sections never hold text)."""
    if is_message:
        return payload
    if p.form == "ag_message" and payload == p.payload:
        return payload
    lead = p.lead if p.form != "ag_message" else default_lead
    code = exit_code if exit_code is not None else (p.exit_code if p.exit_code is not None else 0)
    if payload.strip() == "":
        if p.form == "ag_split":
            x = p.extra
            return f"{lead}{_ag_status(code)}{p.mid}{x['stdout']}{x['mid2']}{x['stderr']}{x['end']}" \
                if payload == p.payload else f"{lead}{_ag_status(code)}{p.mid}{x['mid2']}{x['end']}"
        return f"{lead}{_ag_status(code)}{AG_SPLIT_MID}{AG_SPLIT_MID2}\n"
    mid = p.mid if p.form == "ag_output" else AG_OUTPUT_MID
    return f"{lead}{_ag_status(code)}{mid}{payload}"


def _envelope(text: str) -> tuple[str, bool] | None:
    """Antigravity's ``{"output": ...}`` envelope: its text, and how it was encoded (ASCII-escaped or
    not); None when the text is no such envelope. An envelope that would not come back byte for byte
    when encoded again can't be rebuilt."""
    s = text
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    if not (isinstance(obj, dict) and set(obj) == {"output"} and isinstance(obj["output"], str)):
        return None
    for ascii_only in (True, False):
        if json.dumps(obj, ensure_ascii=ascii_only) == s:
            return obj["output"], ascii_only
    raise Unbuildable("Antigravity result envelope does not encode back to the same bytes")


def _sysmsg_cut(text: str) -> int:
    """Where the harness's appended ``<SYSTEM_MESSAGE>`` notices start (``len(text)`` when there are none),
    the same cut as ``extract.split_system_messages``."""
    from swarmbench.studies.auditor.extract import _SYSMSG, _SYSMSG_INTRO

    if not _SYSMSG.search(text):
        return len(text)
    m = _SYSMSG_INTRO.search(text)
    return m.start() if m else text.find("<SYSTEM_MESSAGE>")


_TASK_LOG_TAIL = re.compile(r"\n*Log: file://\S*\s*\Z")


def find_task_notice(text: str, task_id: str) -> tuple[int, int] | None:
    """The span of a background task's result inside its finish notice ("Task id X finished with
    result: ..."), without the newlines around it and the "Log: file://..." line after it."""
    found = task_notice(text, task_id)
    return found[1] if found else None


def task_notice(text: str, task_id: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """(span of the notice's verb, span of the task's result) in a finish notice. The verb is "failed"
    when the result is one of the harness's own error messages (a time-out) and "finished" otherwise,
    a non-zero exit code included (so the logs show)."""
    m = re.search(r'content=Task id "' + re.escape(task_id) + r'" (?P<verb>finished|failed)(?: with result)?:?', text)
    if not m:
        return None
    end = text.find("</SYSTEM_MESSAGE>", m.end())
    end = len(text) if end < 0 else end
    seg = text[m.end():end]
    log = _TASK_LOG_TAIL.search(seg)
    body = seg[: log.start()] if log else seg
    start = m.end() + (len(body) - len(body.lstrip("\n")))
    stop = m.end() + len(body.rstrip("\n"))
    return (m.span("verb"), (start, max(start, stop)))


# Codex ---------------------------------------------------------------------------------------------------

_CODEX_HEADER = re.compile(
    r"\A(?:Script (?:completed|failed)|Script running with cell ID \d+)\nWall time:? [\d.]+ seconds\nOutput:\n\n?")
_CODEX_HEADER_PART = re.compile(
    r"\A(?:Script (?:completed|failed)|Script running with cell ID \d+)\nWall time:? [\d.]+ seconds\nOutput:\n\Z")


def _json_string_spans(text: str, key: str) -> list[tuple[int, int]]:
    """Spans of the string values of ``key`` anywhere in a JSON text (quotes included)."""
    from json.decoder import scanstring

    out = []
    for m in re.finditer(r'"' + re.escape(key) + r'"\s*:\s*"', text):
        start = m.end() - 1
        try:
            _, end = scanstring(text, start + 1)
        except ValueError:
            continue
        out.append((start, end))
    return out


def codex_chunk(text: str) -> dict[str, Any] | None:
    """A Codex output chunk that is a JSON object holding exactly one ``output`` text (at any depth): where
    that text and the exit code are, and their values. None for a plain-text chunk."""
    from json.decoder import scanstring

    s = text.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return None
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    spans = _json_string_spans(text, "output")
    if not isinstance(obj, dict) or len(spans) != 1:
        return None
    payload, _ = scanstring(text, spans[0][0] + 1)
    codes = [(m.start(1), m.end(1)) for m in re.finditer(r'"exit_code"\s*:\s*(-?\d+)', text)]
    code_span = codes[0] if len(codes) == 1 else None
    exit_code = int(text[code_span[0]:code_span[1]]) if code_span else None
    return {"span": spans[0], "payload": payload, "exit_code": exit_code, "code_span": code_span}


def encode_json_string(value: str) -> str:
    """A JSON string literal as Codex's tool runtime writes one (non-ASCII characters kept as they are)."""
    return json.dumps(value, ensure_ascii=False)


def render_codex_chunk(text: str, info: dict[str, Any], payload: str, exit_code: int | None) -> str:
    edits = [(info["span"], encode_json_string(payload))]
    if exit_code is not None and info.get("code_span"):
        edits.append((info["code_span"], str(exit_code)))
    out = text
    for (a, b), new in sorted(edits, key=lambda e: e[0][0], reverse=True):
        out = out[:a] + new + out[b:]
    return out


# --- the prediction's own payload ---------------------------------------------------------------------------


@dataclass
class Prediction:
    payload: str
    exit_code: int | None
    """The exit code the prediction's own wrapper shows, when it copied one."""
    is_message: bool = False
    """Antigravity: the prediction is one of the harness's own messages (a time-out), not an output."""
    chunks: list[dict[str, Any]] | None = None
    """Codex: the prediction's JSON chunks, when it copied several."""


def strip_prediction(harness: str, function: str, text: str | None) -> Prediction:
    """The auditor's predicted output without any wrapper it copied from the history (it was shown earlier
    outputs with their wrappers, so some answers copy them)."""
    from swarmbench.studies.auditor.extract import unwrap_envelope

    text = "" if text is None else str(text)
    if harness == "claude_code":
        body = _CC_REMINDERS.sub("", text) if "<system-reminder>" in text else text
        if function in ("Bash", "bash"):
            if body.startswith("Exit code"):
                # the "[error: ...]" line the history showed after a failed command's output (the judge's
                # ledger adds it) is not part of what the agent sees
                body = _CC_ERROR_SUFFIX.sub("", body)
            e = _CC_EXIT_LINE.match(body)
            if e:
                return Prediction(body[e.end():], int(e.group(1)))
        return Prediction(body, None)
    if harness == "antigravity":
        inner = unwrap_envelope(text)
        inner = inner[:_sysmsg_cut(inner)]
        if function != "run_command":
            return Prediction(inner, None)
        for candidate in (inner, AG_LEAD + inner.lstrip()):
            p = split_ag(candidate)
            if p.form != "ag_message":
                return Prediction(p.payload, p.exit_code)
        return Prediction(inner, None, is_message=bool(_AG_HARNESS_MESSAGE.match(inner)))
    if harness == "codex":
        body = _CODEX_HEADER.sub("", text, count=1)
        lines = [ln for ln in body.split("\n") if ln.strip()]
        infos = [codex_chunk(ln) for ln in lines]
        if len(lines) > 1 and all(infos):
            return Prediction(body, None, chunks=[{"text": ln, **i} for ln, i in zip(lines, infos, strict=True)])
        one = codex_chunk(body)
        if one is not None:
            return Prediction(one["payload"], one["exit_code"])
        return Prediction(body, None)
    return Prediction(text, None)


# --- swapping the payload of one message ----------------------------------------------------------------------


def _get_text(m: dict[str, Any]) -> str:
    content = m.get("content")
    if isinstance(content, str):
        return content
    texts = [c for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
    others = [c for c in content or [] if not (isinstance(c, dict) and c.get("type") == "text")]
    if len(texts) != 1 or others:
        raise Unbuildable("tool result is not a single text")
    return texts[0]["text"]


def _set_text(m: dict[str, Any], text: str) -> None:
    if isinstance(m.get("content"), str):
        m["content"] = text
        return
    for c in m["content"]:
        if isinstance(c, dict) and c.get("type") == "text":
            c["text"] = text
            return


@dataclass
class Swap:
    message: dict[str, Any]
    real_payload: str
    new_payload: str
    real_exit: int | None
    new_exit: int | None
    form: str


def _choose_exit(answer_exit: int | None, pred: Prediction, real_exit: int | None) -> int | None:
    """The exit code the swapped result shows: the auditor's stated exit code, else the one its predicted
    output shows, else the real one."""
    if answer_exit is not None:
        return answer_exit
    if pred.exit_code is not None:
        return pred.exit_code
    return real_exit


def swap_cc(m: dict[str, Any], function: str, pred: Prediction, answer_exit: int | None) -> Swap:
    text = _get_text(m)
    p = split_cc(text, function)
    new_exit = _choose_exit(answer_exit, pred, p.exit_code) if p.form == "exit_line" else None
    new_text = render_cc(p, pred.payload, new_exit)
    out = copy.deepcopy(m)
    _set_text(out, new_text)
    err = m.get("error")
    if p.form == "exit_line" and p.exit_code is not None:
        want_error = new_exit not in (None, 0)
    else:
        want_error = err is not None  # a non-shell tool or a harness message: keep the real error state
    if want_error:
        body_only = new_text[: len(new_text) - len(p.tail)] if p.tail else new_text
        if isinstance(err, dict):
            if err.get("message") == text:
                message = new_text
            elif err.get("message") == text[: len(text) - len(p.tail)]:
                message = body_only
            else:
                raise Unbuildable("Claude Code error message differs from the result text")
            out["error"] = {**err, "message": message}
        else:
            out["error"] = {"type": "unknown", "message": new_text}
    elif out.get("error") is not None:
        out["error"] = None
    return Swap(out, p.payload, pred.payload, p.exit_code, new_exit, p.form)


def swap_ag(m: dict[str, Any], function: str, pred: Prediction, answer_exit: int | None,
            task_id: str | None = None) -> Swap:
    text = _get_text(m)
    env = _envelope(text)
    inner, ascii_only = env if env is not None else (text, None)
    verb = None
    if task_id:
        found = task_notice(inner, task_id)
        if found is None:
            raise Unbuildable("background task's finish notice not found")
        verb, (a, b) = found
        default_lead = "\t\t\t\t"
    else:
        a, b = 0, _sysmsg_cut(inner)
        default_lead = AG_LEAD
    if function != "run_command":  # other tools print their answer with no status line
        p = Parts("plain", inner[a:b], None)
        new_own, shown = pred.payload, None
    else:
        p = split_ag(inner[a:b])
        new_exit = _choose_exit(answer_exit, pred, p.exit_code)
        new_own = render_ag(p, pred.payload, new_exit, is_message=pred.is_message, default_lead=default_lead)
        shown = None if split_ag(new_own).form == "ag_message" else new_exit
    new_inner = inner[:a] + new_own + inner[b:]
    if verb is not None:
        word = "failed" if split_ag(new_own).form == "ag_message" else "finished"
        if inner[verb[0]:verb[1]] != word and new_own != inner[a:b]:
            new_inner = new_inner[:verb[0]] + word + new_inner[verb[1]:]
    new_text = new_inner if env is None else json.dumps({"output": new_inner}, ensure_ascii=bool(ascii_only))
    out = copy.deepcopy(m)
    _set_text(out, new_text)
    return Swap(out, p.payload, pred.payload, p.exit_code, shown, p.form)


def swap_codex(m: dict[str, Any], pred: Prediction, answer_exit: int | None) -> Swap:
    content = m.get("content")
    out = copy.deepcopy(m)
    if isinstance(content, str):
        h = _CODEX_HEADER.match(content)
        if not h:
            raise Unbuildable("Codex result without its header")
        parts = [content[: h.end()], content[h.end():]]
    else:
        if any(not (isinstance(c, dict) and c.get("type") == "text") for c in content or []):
            raise Unbuildable("Codex result with non-text parts")
        parts = [c["text"] for c in content]
        if not parts or not _CODEX_HEADER_PART.match(parts[0]):
            raise Unbuildable("Codex result without its header")
    chunks = parts[1:]
    infos = [codex_chunk(c) for c in chunks]
    if len(chunks) == 1:
        info = infos[0]
        if info is not None:
            new_exit = _choose_exit(answer_exit, pred, info["exit_code"])
            new_chunks = [render_codex_chunk(chunks[0], info, pred.payload, new_exit)]
            real_payload, real_exit = info["payload"], info["exit_code"]
            new_exit = new_exit if info.get("code_span") else None
        else:
            new_chunks, real_payload, real_exit, new_exit = [pred.payload], chunks[0], None, None
        new_payload = pred.payload
    elif pred.chunks and len(pred.chunks) == len(chunks) and all(infos):
        new_chunks = [render_codex_chunk(c, i, pc["payload"], pc["exit_code"])
                      for c, i, pc in zip(chunks, infos, pred.chunks, strict=True)]
        real_payload = "\n".join(i["payload"] for i in infos)
        new_payload = "\n".join(pc["payload"] for pc in pred.chunks)
        real_exit = new_exit = None
    else:
        raise Unbuildable(f"Codex result in {len(chunks)} chunks that the prediction doesn't mirror")
    if isinstance(content, str):
        out["content"] = parts[0] + new_chunks[0]
    else:
        for c, new in zip(out["content"][1:], new_chunks, strict=True):
            c["text"] = new
    return Swap(out, real_payload, new_payload, real_exit, new_exit, "codex")


def swap_payload(harness: str, function: str, message: dict[str, Any], pred: Prediction,
                 answer_exit: int | None = None, task_id: str | None = None) -> Swap:
    """The message with its payload replaced by the prediction's (see the module docstring)."""
    if harness == "claude_code":
        return swap_cc(message, function, pred, answer_exit)
    if harness == "antigravity":
        return swap_ag(message, function, pred, answer_exit, task_id)
    if harness == "codex":
        return swap_codex(message, pred, answer_exit)
    raise Unbuildable(f"no payload rules for harness {harness}")


def real_prediction(harness: str, function: str, message: dict[str, Any], task_id: str | None = None) -> Prediction:
    """The real result's own payload and exit code, as a prediction: swapping it in must give the message
    back byte for byte (the R input, and the check on the swap rules)."""
    if harness == "claude_code":
        p = split_cc(_get_text(message), function)
        return Prediction(p.payload, p.exit_code)
    if harness == "antigravity":
        text = _get_text(message)
        env = _envelope(text)
        inner = env[0] if env else text
        if task_id:
            span = find_task_notice(inner, task_id)
            if span is None:
                raise Unbuildable("background task's finish notice not found")
            own = inner[span[0]:span[1]]
        else:
            own = inner[:_sysmsg_cut(inner)]
        if function != "run_command":
            return Prediction(own, None)
        p = split_ag(own)
        return Prediction(p.payload, p.exit_code)
    if harness == "codex":
        content = message.get("content")
        parts = [content] if isinstance(content, str) else [c.get("text", "") for c in content]
        chunks = parts[1:] if not isinstance(content, str) else [_CODEX_HEADER.sub("", content, count=1)]
        infos = [codex_chunk(c) for c in chunks]
        if len(chunks) == 1:
            return Prediction(infos[0]["payload"], infos[0]["exit_code"]) if infos[0] else Prediction(chunks[0], None)
        if all(infos):
            return Prediction("\n".join(chunks), None, chunks=[{"text": c, **i} for c, i in zip(chunks, infos, strict=True)])
        raise Unbuildable(f"Codex result in {len(chunks)} chunks that are not all JSON")
    raise Unbuildable(f"no payload rules for harness {harness}")


# --- finding the target and building the two inputs ---------------------------------------------------------


def _call_content(args: Any) -> str:
    """A call's arguments without those set to False or None (a harness may fill such defaults in when it
    sends a call back), as in the judge's ledger."""
    if not isinstance(args, dict):
        return json.dumps(args, sort_keys=True, default=str)
    return json.dumps({k: v for k, v in args.items() if v is not False and v is not None}, sort_keys=True,
                      default=str)


def call_id_of(key: str) -> str:
    """The tool-call id in a commands-table key (``run/agent/call_id``, ``~N`` added for a repeated id)."""
    return key.rsplit("/", 1)[-1].split("~", 1)[0]


def locate_target(case: dict[str, Any], event: dict[str, Any]) -> int:
    """The position, in the next model call's input, of the message carrying the target result."""
    inputs = event.get("input") or []
    harness, task = case["harness"], case.get("task_id")
    if harness == "antigravity" and case.get("background"):
        if not task:
            raise Unbuildable("background task without a task id")
        found = [i for i, m in enumerate(inputs) if find_task_notice(_inner_text(m), task)]
        if not found:
            raise Unbuildable("background task's finish notice not in the next call's input")
        i = found[-1]
        a, b = find_task_notice(_inner_text(inputs[i]), task)
        if _inner_text(inputs[i])[a:b] != case["output"]:
            raise Unbuildable("finish notice differs from the recorded output")
        return i
    call_id = call_id_of(case["key"])
    try:
        args = json.loads(case.get("arguments") or "{}")
    except ValueError:
        args = None
    want = _call_content(args)
    turn, made_id = None, None
    for i in range(len(inputs) - 1, -1, -1):
        m = inputs[i]
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            if tc.get("id") == call_id or (tc.get("function") == case["function"]
                                           and _call_content(tc.get("arguments")) == want):
                turn, made_id = i, tc.get("id")
                break
        if turn is not None:
            break
    found = []
    if turn is not None:
        found = [i for i in range(turn + 1, len(inputs))
                 if inputs[i].get("role") == "tool" and inputs[i].get("tool_call_id") == made_id]
    if not found:
        found = [i for i, m in enumerate(inputs) if m.get("role") == "tool"
                 and recorded_output(harness, message_text(m)) == case["output"]][-1:]
    if not found:
        raise Unbuildable("target result not found in the next call's input")
    i = found[0]
    if recorded_output(harness, message_text(inputs[i])) != case["output"]:
        raise Unbuildable("target result's text differs from the recorded output")
    return i


def _inner_text(m: dict[str, Any]) -> str:
    try:
        text = _get_text(m)
    except Unbuildable:
        return message_text(m)
    try:
        env = _envelope(text)
    except Unbuildable:
        return text
    return env[0] if env else text


@dataclass
class Built:
    """One case's two inputs (A: the auditor's output; R: the real one), with what is needed to send them."""

    case_id: str
    ok: bool
    reason: str | None = None
    model: str | None = None
    a_input: list[dict[str, Any]] | None = None
    r_input: list[dict[str, Any]] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any = None
    config: dict[str, Any] | None = None
    logged_output: dict[str, Any] | None = None
    target_index: int | None = None
    checks: dict[str, Any] = field(default_factory=dict)


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=False)


def build_case(case: dict[str, Any], sl: LogSlice) -> Built:
    """Find the target result in the agent's next model call and build the A and R inputs."""
    from inspect_ai.event._validate import validate_chat_messages

    cid = case["case_id"]
    event = sl.events.get(case["result_event"])
    if event is None:
        return Built(cid, False, "next model call not in the log")
    checks: dict[str, Any] = {}
    try:
        idx = locate_target(case, event)
        msg = event["input"][idx]
        task = case.get("task_id") if case["harness"] == "antigravity" and case.get("background") else None
        # the first model event whose input carries the target message must be this one
        positions = sl.pool_index.get(case["result_event"]) or []
        checks["first_carrier"] = None  # can't be checked when the log keeps inputs whole instead of pooled
        if positions:
            p = positions[idx]
            carriers = sorted((mm for mm in sl.meta if mm.covers(p)), key=lambda mm: pd_ts(mm.timestamp))
            checks["first_carrier"] = carriers[0].uuid == case["result_event"] if carriers else False
            checks["carriers"] = len(carriers)
        owner = owner_of(event.get("span_id"), sl.spans, set(sl.agents))
        checks["owner"] = owner
        checks["owner_is_agent"] = owner == case["agent"]
        if checks["first_carrier"] is False:
            raise Unbuildable("an earlier model call already carried the result: not the agent's next call")
        if not checks["owner_is_agent"]:
            raise Unbuildable(f"the next call sits in {owner}'s span, not {case['agent']}'s")
        real = real_prediction(case["harness"], case["function"], msg, task)
        r_swap = swap_payload(case["harness"], case["function"], msg, real, None, task)
        checks["r_identical"] = _dump(r_swap.message) == _dump(msg)
        copied = strip_prediction(case["harness"], case["function"], case["output"])
        try:
            checks["copy_identical"] = _dump(swap_payload(case["harness"], case["function"], msg, copied, None,
                                                          task).message) == _dump(msg)
        except Unbuildable:
            checks["copy_identical"] = False
        if not checks["r_identical"]:
            raise Unbuildable("swapping the real payload back in does not give the logged message")
        pred = strip_prediction(case["harness"], case["function"], case["predicted_output"])
        pe = case.get("predicted_exit_code")
        pe = None if pe is None or (isinstance(pe, float) and math.isnan(pe)) else int(pe)
        a_swap = swap_payload(case["harness"], case["function"], msg, pred, pe, task)
    except Unbuildable as exc:
        return Built(cid, False, str(exc), checks=checks)
    a_input = list(event["input"])
    a_input[idx] = a_swap.message
    r_input = list(event["input"])
    differs = [i for i, (x, y) in enumerate(zip(a_input, r_input, strict=True)) if _dump(x) != _dump(y)]
    checks.update(
        a_differs_at=differs,
        form=a_swap.form,
        real_exit=a_swap.real_exit,
        new_exit=a_swap.new_exit,
        real_payload_chars=len(a_swap.real_payload),
        new_payload_chars=len(a_swap.new_payload),
        payload_same=a_swap.real_payload == a_swap.new_payload,
        prediction_is_message=pred.is_message,
        n_input=len(r_input),
        turn_results=sum(1 for m in r_input[idx:] if m.get("role") == "tool"),
    )
    try:
        validate_chat_messages(a_input, context={"deserializing": True})
        validate_chat_messages(r_input, context={"deserializing": True})
    except Exception as exc:  # pragma: no cover - would mean a malformed rebuild
        return Built(cid, False, f"rebuilt input is not valid Inspect messages: {exc}", checks=checks)
    return Built(cid, True, None, model=event.get("model"), a_input=a_input, r_input=r_input,
                 tools=event.get("tools"), tool_choice=event.get("tool_choice"), config=event.get("config"),
                 logged_output=event.get("output"), target_index=idx, checks=checks)


def pd_ts(value: str) -> Any:
    import pandas as pd

    return pd.Timestamp(value) if value else pd.Timestamp.min.tz_localize("UTC")


def inspect_view(log_path: Path, uuids: Iterable[str]) -> dict[str, dict[str, str]]:
    """The named model events as Inspect's own reader gives them (attachments resolved), serialized: the
    reference for the byte-for-byte check. Loads the whole log, so only for small logs."""
    from inspect_ai.log import read_eval_log

    want = set(uuids)
    sample = read_eval_log(str(log_path), resolve_attachments=True).samples[0]
    out = {}
    for e in sample.events:
        if getattr(e, "event", None) == "model" and e.uuid in want:
            out[e.uuid] = {
                "input": _dump([m.model_dump(mode="json") for m in e.input]),
                "tools": _dump([t.model_dump(mode="json") for t in e.tools]),
                "config": _dump(e.config.model_dump(mode="json")),
            }
    del sample
    return out


def inspect_serialized(built: Built) -> dict[str, str]:
    """A built R input, tools and config, serialized the same way as ``inspect_view``."""
    from inspect_ai.event._validate import validate_chat_messages
    from inspect_ai.model import GenerateConfig
    from inspect_ai.tool import ToolInfo

    msgs = validate_chat_messages(built.r_input, context={"deserializing": True})
    return {
        "input": _dump([m.model_dump(mode="json") for m in msgs]),
        "tools": _dump([ToolInfo.model_validate(t).model_dump(mode="json") for t in built.tools or []]),
        "config": _dump(GenerateConfig.model_validate(built.config or {}).model_dump(mode="json")),
    }


def sample_json_size(log_path: Path) -> int:
    """The uncompressed size of a log's sample (to decide whether Inspect's reader can load it)."""
    z, name = _zip(log_path)
    try:
        return z.getinfo(name).file_size
    finally:
        z.close()
