"""Which agent the current code is running for.

Set at the start of each agent's task, so everything that agent's task starts
(its tools, its bridge's service task, approval checks of its bridged tool calls)
sees the same value.
"""

from __future__ import annotations

from contextvars import ContextVar

_current_agent: ContextVar[str | None] = ContextVar("swarmbench_current_agent", default=None)


def current_agent() -> str | None:
    """Name of the agent (span name, e.g. ``agent-3``) whose task is running, or None."""
    return _current_agent.get()


def set_current_agent(name: str | None) -> None:
    _current_agent.set(name)
