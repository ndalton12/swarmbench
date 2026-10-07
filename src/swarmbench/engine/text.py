"""Scenario text shown to agents: relative-date placeholders and per-agent fields."""

from __future__ import annotations

from datetime import datetime

from swarmbench.design import render_dates as _render_dates


def render_dates(text: str, run_start: datetime) -> str:
    """Fill in date placeholders such as ``{{date:-2wd 09:14|rfc2822}}``."""
    return _render_dates(text, run_start)


def render_prompt(template: str, user: str, host: str, users: list[str]) -> str:
    """Fill in {user}, {host} and {users}; any other braces are left alone."""
    return template.replace("{user}", user).replace("{host}", host).replace("{users}", ", ".join(users))
