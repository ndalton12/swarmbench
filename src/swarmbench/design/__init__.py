"""Scenario design support.

Scenarios are designed by a coding agent following ``.claude/skills/design-scenario/SKILL.md``
(the ``/design-scenario`` skill in Claude Code; ``swarm design`` starts one headless, see
``agent``). This package holds what the agent, the engine and the runner share:

- ``dates``: relative-date placeholders in workspace files (``{{date:-2wd 09:14|rfc2822}}``);
- ``history``: replaying ``history.yaml`` into a backdated git repository;
- ``checks``: folder checks used by ``swarm check`` (git history, dates, sizes, a word check
  for test-like vocabulary);
- ``evidence`` and ``signals``: what past runs showed, for ``swarm design evidence`` and screens.
"""

from __future__ import annotations

from swarmbench.design.dates import check_dates, render_dates
from swarmbench.design.history import check_history, seed_workspace

__all__ = ["check_dates", "check_history", "render_dates", "seed_workspace"]
