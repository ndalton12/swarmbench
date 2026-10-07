"""Scenario text shown to agents: relative-date placeholders and per-agent fields."""

from __future__ import annotations

from datetime import datetime


def render_dates(text: str, run_start: datetime) -> str:
    """Fill in date placeholders such as ``{{date:-2wd 09:14|rfc2822}}`` (designer's helper, if present)."""
    try:
        from swarmbench.design import render_dates as _render  # type: ignore[attr-defined]
    except ImportError:
        return text
    return _render(text, run_start)


def render_prompt(template: str, user: str, host: str, users: list[str]) -> str:
    """Fill in {user}, {host} and {users}; any other braces are left alone."""
    return template.replace("{user}", user).replace("{host}", host).replace("{users}", ", ".join(users))
