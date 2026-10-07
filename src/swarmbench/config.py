"""Scenario configuration: loading, defaults, variants and command-line overrides.

A scenario is a folder containing ``scenario.yaml`` plus the files it refers
to (a prompt file, a workspace folder, an optional protected folder and a
notes file for the judge). Every scenario is normalised into a list of teams:
a single-swarm scenario written with ``swarm:`` becomes one team named
``swarm``.

Precedence, highest first: command-line overrides, team settings, the
``swarm:`` block, built-in defaults.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Harness = Literal["react", "claude_code", "codex_cli"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Messaging = Literal["direct", "board", "both", "off"]
Delivery = Literal["notice", "on_request"]

DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"
MAX_AGENTS_PER_RUN = 64


def parse_count(value: Any) -> int:
    """Parse token counts like ``2M``, ``500k`` or ``1_000_000``."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lower().replace("_", "").replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", text)
    if not match:
        raise ValueError(f"not a token count: {value!r}")
    number, suffix = float(match.group(1)), match.group(2)
    return int(number * {"": 1, "k": 1_000, "m": 1_000_000}[suffix])


def parse_duration(value: Any) -> int:
    """Parse durations like ``90m``, ``2h``, ``45s`` or plain seconds into seconds."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", text)
    if not match:
        raise ValueError(f"not a duration: {value!r}")
    number, suffix = float(match.group(1)), match.group(2)
    return int(number * {"": 1, "s": 1, "m": 60, "h": 3600}[suffix])


def _messaging(v: Any) -> Any:
    if v is True:
        return "direct"
    if v is False:
        return "off"
    return v


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SwarmSettings(_Strict):
    """Settings shared by every agent in a team (teams can override them)."""

    agents: int = Field(default=4, ge=1, le=MAX_AGENTS_PER_RUN)
    model: str = DEFAULT_MODEL
    effort: Effort | None = None
    harness: Harness = "react"
    token_budget: int = 30_000_000
    """Total tokens for the team, split evenly between its agents. Cached rereads of the
    conversation count too, and they are most of an agent's tokens, so budgets need to be
    large; the scenario's ``max_cost`` is the practical spending limit."""
    messaging: Messaging = "direct"
    """direct: in-memory message tools. board: shared message board stored as
    files in the shared volume, used with a ``board`` command. both, or off."""
    delivery: Delivery | None = None
    """How agents learn of new messages. None means the default for the route:
    ``notice`` for direct messages, ``on_request`` for the board."""

    @field_validator("token_budget", mode="before")
    @classmethod
    def _budget(cls, v: Any) -> int:
        return parse_count(v)

    @field_validator("messaging", mode="before")
    @classmethod
    def _msg(cls, v: Any) -> Any:
        return _messaging(v)


class Team(_Strict):
    """One swarm. Unset fields inherit from the scenario's ``swarm`` block."""

    name: str
    agents: int | None = Field(default=None, ge=1, le=MAX_AGENTS_PER_RUN)
    model: str | None = None
    effort: Effort | None = None
    harness: Harness | None = None
    token_budget: int | None = None
    messaging: Messaging | None = None
    delivery: Delivery | None = None
    prompt: str | None = None
    """Prompt file for this team, relative to the scenario folder."""
    workspace: str | None = None
    """Workspace folder for this team, relative to the scenario folder."""

    @field_validator("token_budget", mode="before")
    @classmethod
    def _budget(cls, v: Any) -> int | None:
        return None if v is None else parse_count(v)

    @field_validator("messaging", mode="before")
    @classmethod
    def _msg(cls, v: Any) -> Any:
        return _messaging(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", v):
            raise ValueError("team names must be short lowercase identifiers")
        return v


class Encounter(_Strict):
    """How and when separate teams can discover each other."""

    after: int = 1800
    """Seconds after start when the channel opens."""
    via: Literal["shared_dir", "board_channel", "file"] = "shared_dir"
    """shared_dir: a folder mounted into every team's containers appears.
    board_channel: a board channel every team can read and post to appears.
    file: ``source`` (from the scenario folder) is copied into every team's workspace."""
    path: str | None = None
    """Container path (shared_dir), channel name (board_channel) or destination path (file)."""
    source: str | None = None
    """For ``file``: file in the scenario folder to copy."""
    announce: str | None = None
    """Optional text posted by an event sender when the channel opens (None: silent)."""

    @field_validator("after", mode="before")
    @classmethod
    def _after(cls, v: Any) -> int:
        return parse_duration(v)


class Advanced(_Strict):
    """Rarely needed overrides. Example scenarios should not need this block."""

    sandbox_image: str | None = None
    runtime: str | None = None
    """Docker runtime, e.g. ``runsc`` for gVisor on Linux hosts."""
    memory_per_agent_mb: int | None = None
    """Container memory is this times the team's agent count. None: a default per harness."""
    cpus: float | None = None
    """CPUs for each team container. None: scales with agent count."""
    hostname: str | None = None
    """Hostname for team containers (realism: no 'agent' or 'sandbox' in names). None: a default."""
    username_pattern: str = "u{n:02d}"
    """Linux user name for agent n."""
    monitor_model: str | None = None
    """Small model used to score ambiguous tool calls (None disables model scoring)."""
    monitor_stop_on: Literal["critical", "high", "never"] = "critical"
    judge_model: str | None = None
    judge_max_cost: float | None = None
    """Hard dollar cap on judging each sample (epoch). None: the costs.judge_allowance of
    max_cost, or $10 when the scenario has no max_cost."""
    scanners: list[str] | None = None
    """Names of judge scanners to run (None means the default set)."""
    compaction: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)
    """Free-form settings for scenario-specific engine hooks."""


class Scenario(_Strict):
    name: str
    description: str = ""
    prompt: str = "prompt.md"
    workspace: str | None = "workspace"
    protected: str | None = None
    """Folder mounted read-only at /opt in every container (e.g. a checker). Defaults to
    ``protected/`` if that folder exists."""
    notes: str = "notes.md"
    """For the judge and designers only; never shown to agents."""
    swarm: SwarmSettings = Field(default_factory=SwarmSettings)
    teams: list[Team] | None = None
    encounter: Encounter | None = None
    time_limit: int = 3600
    max_cost: float | None = None
    """Dollar cap per swarm run (Inspect cost_limit). None means no cap."""
    epochs: int = 1
    advanced: Advanced = Field(default_factory=Advanced)

    # Set by load_scenario; not part of the YAML.
    root: Path | None = Field(default=None, exclude=True)

    @field_validator("time_limit", mode="before")
    @classmethod
    def _time(cls, v: Any) -> int:
        return parse_duration(v)

    @model_validator(mode="after")
    def _validate(self) -> Scenario:
        teams = self.resolved_teams()
        names = [t.name for t in teams]
        if len(set(names)) != len(names):
            raise ValueError("team names must be unique")
        total = sum(t.agents for t in teams)
        if total > MAX_AGENTS_PER_RUN:
            raise ValueError(f"{total} agents in total; the limit per run is {MAX_AGENTS_PER_RUN}")
        if self.encounter and len(teams) < 2:
            raise ValueError("encounter needs at least two teams")
        return self

    @property
    def multi_team(self) -> bool:
        return bool(self.teams and len(self.teams) > 1)

    def resolved_teams(self) -> list[ResolvedTeam]:
        """Every team with inherited settings filled in."""
        base = self.swarm
        teams = self.teams or [Team(name="swarm")]
        multi = len(teams) > 1
        out = []
        for t in teams:
            messaging = base.messaging if t.messaging is None else t.messaging
            out.append(
                ResolvedTeam(
                    name=t.name,
                    agents=t.agents or base.agents,
                    model=t.model or base.model,
                    effort=t.effort or base.effort,
                    harness=t.harness or base.harness,
                    token_budget=t.token_budget or base.token_budget,
                    messaging=messaging,
                    delivery=t.delivery or base.delivery,
                    prompt=t.prompt or self.prompt,
                    workspace=t.workspace if t.workspace is not None else self.workspace,
                    multi_team=multi,
                )
            )
        return out

    def path(self, relative: str) -> Path:
        assert self.root is not None, "scenario was not loaded from a folder"
        return self.root / relative

    def protected_dir(self) -> Path | None:
        if self.root is None:
            return None
        if self.protected:
            return self.root / self.protected
        default = self.root / "protected"
        return default if default.is_dir() else None


class ResolvedTeam(_Strict):
    name: str
    agents: int
    model: str
    effort: Effort | None
    harness: Harness
    token_budget: int
    messaging: Messaging
    delivery: Delivery | None
    prompt: str
    workspace: str | None
    multi_team: bool

    @property
    def per_agent_tokens(self) -> int:
        return self.token_budget // self.agents

    def agent_names(self) -> list[str]:
        """Agent identifiers. Prefixed with the team name when there are several teams."""
        prefix = f"{self.name}-" if self.multi_team else ""
        return [f"{prefix}agent-{i + 1}" for i in range(self.agents)]


def _set_dotted(data: dict[str, Any], key: str, value: Any) -> None:
    target = data
    *parents, leaf = key.split(".")
    for p in parents:
        target = target.setdefault(p, {})
    target[leaf] = value


def load_scenario(path: str | Path, overrides: dict[str, Any] | None = None) -> Scenario:
    """Load a scenario folder (or a YAML file inside one) and apply overrides.

    ``overrides`` uses dotted keys, e.g. ``{"swarm.agents": 8, "time_limit": "2h"}``.
    Keys with a value of None are ignored, so CLI flags can be passed straight in.
    """
    path = Path(path)
    file = path / "scenario.yaml" if path.is_dir() else path
    if not file.exists():
        raise FileNotFoundError(f"no scenario.yaml at {file}")
    data = yaml.safe_load(file.read_text()) or {}

    for key, value in (overrides or {}).items():
        if value is not None:
            _set_dotted(data, key, value)

    scenario = Scenario.model_validate(data)
    scenario.root = file.parent.resolve()
    return scenario


def dump_scenario(scenario: Scenario) -> str:
    """The resolved scenario as YAML (used to record exactly what was run)."""
    data = scenario.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False)
