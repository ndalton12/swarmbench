"""The plain-text format the designer model uses to hand back files.

Files are easier for a model to write as tagged blocks than as JSON (no
escaping of long multi-line text)::

    <file path="workspace/README.md">
    ...content...
    </file>
    <delete path="workspace/old.txt"/>

Free-text sections such as ``<critique>...</critique>`` use the same style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_OPEN = re.compile(r'<file\s+path\s*=\s*"([^"]+)"\s*>', re.IGNORECASE)
_CLOSE = re.compile(r"^</file>[ \t]*$", re.IGNORECASE | re.MULTILINE)
_DELETE = re.compile(r'<delete\s+path\s*=\s*"([^"]+)"\s*/?>(?:\s*</delete>)?', re.IGNORECASE)


@dataclass
class Reply:
    """What the model handed back."""

    files: dict[str, str] = field(default_factory=dict)
    """Path (relative to the scenario folder) to full new content."""
    deletes: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    """Files whose block was opened but never closed (usually: the reply was cut off)."""


def parse_reply(text: str) -> Reply:
    reply = Reply()
    pos = 0
    while True:
        start = _OPEN.search(text, pos)
        if not start:
            break
        path = start.group(1).strip()
        body_start = start.end()
        end = _CLOSE.search(text, body_start)
        if not end:
            reply.incomplete.append(path)
            break
        reply.files[path] = _clean_body(text[body_start : end.start()])
        pos = end.end()
    # Deletes are only looked for outside file bodies, so file contents can't trigger them.
    outside = _strip_file_bodies(text)
    reply.deletes = [m.group(1).strip() for m in _DELETE.finditer(outside)]
    return reply


def section(text: str, tag: str) -> str | None:
    """Content of the first ``<tag>...</tag>`` outside file bodies, or None."""
    match = re.search(rf"<{tag}>(.*?)</{tag}>", _strip_file_bodies(text), re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def format_files(files: dict[str, str], readonly: set[str] | None = None) -> str:
    """Show files to the model in the same format it replies in."""
    readonly = readonly or set()
    parts = []
    for path in sorted(files):
        note = ' readonly="true"' if path in readonly else ""
        parts.append(f'<file path="{path}"{note}>\n{files[path].rstrip()}\n</file>')
    return "\n\n".join(parts)


def _strip_file_bodies(text: str) -> str:
    out, pos = [], 0
    while True:
        start = _OPEN.search(text, pos)
        if not start:
            out.append(text[pos:])
            break
        out.append(text[pos : start.start()])
        end = _CLOSE.search(text, start.end())
        if not end:
            break
        pos = end.end()
    return "".join(out)


def _clean_body(body: str) -> str:
    if body.startswith("\r\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    lines = body.rstrip().split("\n")
    # Models sometimes wrap a whole file in a code fence; remove it.
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        lines = lines[1:-1]
    text = "\n".join(lines)
    return text + "\n" if text else ""
