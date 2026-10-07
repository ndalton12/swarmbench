"""Dates in scenario files, written relative to the run start.

A fixed date in a workspace file goes stale: an email from "last Tuesday"
that is months old is a giveaway. Files therefore say::

    {{date:-2wd 09:14|rfc2822}}     two working days before the run, 09:14 local time
    {{date:+2wd|%A}}                the weekday name two working days after the run starts
    {{date:-36h}}                   36 hours before the run start, ISO 8601
    {{date:0d 08:30|date}}          the run's own day, as 2026-10-07

Offset units: ``d`` (calendar days), ``wd`` (working days, skipping Saturday
and Sunday) and ``h`` (hours). An optional ``HH:MM`` sets the local time of
day; otherwise the run start's time is kept. Formats: ``iso`` (the default),
``rfc2822`` (for .eml Date headers), ``date``, ``time``, ``weekday``, or any
strftime pattern. Negative offsets are always in the past; ``0d HH:MM`` can be
in the future if the run starts earlier in the day.

``render_dates`` is applied to every text file when the workspace is seeded
(including earlier versions in git history), so all files agree with each other.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

PLACEHOLDER = re.compile(r"\{\{date:([^|}]*)(?:\|([^}]*))?\}\}")
_SPEC = re.compile(r"^\s*(?:([+-]?\d+)(wd|d|h))?\s*(?:([01]?\d|2[0-3]):([0-5]\d))?\s*$")
_NAMED = {"date": "%Y-%m-%d", "time": "%H:%M", "weekday": "%A"}


def render_dates(text: str, now: datetime) -> str:
    """Replace every ``{{date:...}}`` placeholder, relative to ``now`` (timezone-aware)."""
    return PLACEHOLDER.sub(lambda m: _format(_resolve(m.group(1), now), m.group(2)), text)


def check_dates(text: str) -> list[str]:
    """Problems with the placeholders in ``text``."""
    errors = []
    for m in PLACEHOLDER.finditer(text):
        if not _SPEC.match(m.group(1)) or not m.group(1).strip():
            errors.append(f"bad date placeholder {m.group(0)!r}: use e.g. {{{{date:-2wd 09:14|rfc2822}}}}")
        fmt = (m.group(2) or "iso").strip()
        if fmt not in ("iso", "rfc2822", *_NAMED) and "%" not in fmt:
            errors.append(
                f"bad date format in {m.group(0)!r}: use iso, rfc2822, date, time, weekday or strftime"
            )
    return errors


def _resolve(spec: str, now: datetime) -> datetime:
    m = _SPEC.match(spec)
    if not m or not spec.strip():
        return now
    amount, unit, hour, minute = m.groups()
    when = now
    if amount is not None:
        n = int(amount)
        if unit == "h":  # elapsed hours, so daylight-saving changes don't distort them
            when = (now.astimezone(UTC) + timedelta(hours=n)).astimezone(now.tzinfo)
        elif unit == "d":
            when = now + timedelta(days=n)
        else:
            step = 1 if n >= 0 else -1
            for _ in range(abs(n)):
                when += timedelta(days=step)
                while when.weekday() >= 5:
                    when += timedelta(days=step)
    if hour is not None:
        when = when.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    # A local time skipped by a daylight-saving change becomes a real one.
    return when.astimezone(UTC).astimezone(now.tzinfo)


def _format(when: datetime, fmt: str | None) -> str:
    fmt = (fmt or "iso").strip()
    if fmt == "iso":
        return when.isoformat(timespec="seconds")
    if fmt == "rfc2822":
        return format_datetime(when)
    return when.strftime(_NAMED.get(fmt, fmt))
