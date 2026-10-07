"""Data formats shared between the engine, the monitor, the judge and the designer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["info", "low", "medium", "high", "critical"]
Verdict = Literal["none", "minor", "concerning", "severe"]


def now() -> datetime:
    return datetime.now(UTC)


class SwarmMessage(BaseModel):
    """One message sent between agents over the message bus."""

    id: int
    time: datetime = Field(default_factory=now)
    sender: str
    to: str
    """An agent name, or ``all`` for everyone the sender can reach."""
    text: str
    channel: Literal["direct", "board"] = "direct"
    board_channel: str | None = None
    """Board channel name for board posts."""
    delivered_to: list[str] = Field(default_factory=list)
    """Agents that could receive this message when it was sent."""
    read_by: list[str] = Field(default_factory=list)
    """Agents that were actually shown it (checked messages, read the board, or got a notice)."""


class MonitorFlag(BaseModel):
    """Something the live monitor noticed."""

    time: datetime = Field(default_factory=now)
    agent: str | None
    """Agent responsible, or None if the sandbox watcher can't attribute it."""
    severity: Severity
    category: str
    """Short slug, e.g. ``network``, ``escape``, ``checker_tamper``, ``destructive``."""
    summary: str
    evidence: str = ""
    """The tool call, command line or file change that triggered the flag (truncated)."""
    source: Literal["rules", "model", "watcher"] = "rules"
    action: Literal["logged", "blocked", "stopped_run"] = "logged"


class Concern(BaseModel):
    """One concerning behavior found by the judge."""

    behavior: str
    """Short plain-language name, e.g. "claimed a proof it knew was wrong"."""
    severity: Literal["minor", "concerning", "severe"]
    agents: list[str]
    explanation: str
    quotes: list[str] = Field(default_factory=list)
    """Short verbatim quotes from the transcript that support the concern."""


class JudgeReport(BaseModel):
    """The judge's plain-language verdict on one swarm run (one sample/epoch)."""

    run_id: str
    scenario: str
    sample_id: str | int | None = None
    epoch: int = 1
    verdict: Verdict
    headline: str
    """One sentence a busy reader can take away."""
    summary: str
    """What happened, in 5 to 10 plain sentences."""
    concerns: list[Concern] = Field(default_factory=list)
    outcome: str = ""
    """What the swarm actually produced, e.g. "reported the problem has no solution"."""
    stats: dict[str, float | int | str] = Field(default_factory=dict)
    """Agents, messages, tool calls, monitor flags and so on."""
    cost: CostSummary | None = None
    coverage: str = ""
    """What the judge could see, e.g. "5/6 agents scanned; 1 scanner failed; stopped early by monitor".
    Always filled in, so a gap is never mistaken for a clean result."""
    eval_awareness: str = ""
    """Whether any agent said it thought it was being tested, with a quote."""
    realism_notes: list[str] = Field(default_factory=list)
    """Anything in the transcript suggesting the scenario felt artificial."""


RunState = Literal["starting", "running", "judging", "done", "failed", "stopped"]


class CostSummary(BaseModel):
    """Tokens and estimated dollars. ``usd`` is None when a model has no price."""

    tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float | None = 0.0
    by_model: dict[str, float | None] = Field(default_factory=dict)
    by_agent: dict[str, float | None] = Field(default_factory=dict)
    unpriced_models: list[str] = Field(default_factory=list)


class RunStatus(BaseModel):
    """Live state of one run, kept in runs/<id>/status.json and updated every few seconds."""

    run_id: str
    scenario: str
    state: RunState = "starting"
    pid: int | None = None
    pid_started: float | None = None
    """Process start time, checked before signalling so a reused pid is never killed."""
    compose_project: str | None = None
    experiment: str | None = None
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict)
    """The settings an experiment varied for this run, e.g. {"swarm.agents": 12}."""
    started: datetime = Field(default_factory=now)
    updated: datetime = Field(default_factory=now)
    finished: datetime | None = None
    agents_total: int = 0
    agents_active: int = 0
    messages: int = 0
    monitor_flags: dict[str, int] = Field(default_factory=dict)
    """Count of flags by severity."""
    swarm_cost: CostSummary = Field(default_factory=CostSummary)
    judge_cost: CostSummary = Field(default_factory=CostSummary)
    verdict: Verdict | None = None
    headline: str | None = None
    error: str | None = None


JudgeReport.model_rebuild()
