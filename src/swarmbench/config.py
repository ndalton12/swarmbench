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

Harness = Literal["react", "claude_code", "codex_cli", "antigravity"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
Messaging = Literal["direct", "board", "both", "off"]
Delivery = Literal["notice", "on_request"]

DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"
MAX_AGENTS_PER_RUN = 128


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


class Role(_Strict):
    """A part one agent plays, such as a specialty. Its prompt file's text is added to that
    agent's system prompt."""

    name: str
    prompt: str
    """File relative to the scenario folder."""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,23}", v):
            raise ValueError("role names must be short lowercase identifiers")
        return v

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, v: str) -> str:
        if v.startswith("/") or ".." in Path(v).parts:
            raise ValueError("role prompt files must be inside the scenario folder")
        return v


def _model_list(models: list[str] | None) -> list[str] | None:
    if models is not None and (not models or any(not m.strip() for m in models)):
        raise ValueError("models must be a non-empty list of model names")
    return models


def _unique_roles(roles: list[Role] | None) -> list[Role] | None:
    if roles and len({r.name for r in roles}) != len(roles):
        raise ValueError("role names must be unique")
    return roles


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
    roles: list[Role] | None = None
    """Roles given out in turn: the team's first agent gets the first role, the second agent
    the second, and so on, starting again from the first when the list runs out."""
    models: list[str] | None = None
    """Models given out in turn, like roles, to mix models in one team. When set, it replaces
    ``model`` (a scenario file may not set both; see load_scenario)."""

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[Role] | None) -> list[Role] | None:
        return _unique_roles(v)

    @field_validator("models")
    @classmethod
    def _models(cls, v: list[str] | None) -> list[str] | None:
        return _model_list(v)

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
    models: list[str] | None = None
    effort: Effort | None = None
    harness: Harness | None = None
    token_budget: int | None = None
    messaging: Messaging | None = None
    delivery: Delivery | None = None
    roles: list[Role] | None = None
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

    @field_validator("roles")
    @classmethod
    def _roles(cls, v: list[Role] | None) -> list[Role] | None:
        return _unique_roles(v)

    @field_validator("models")
    @classmethod
    def _models(cls, v: list[str] | None) -> list[str] | None:
        return _model_list(v)

    @model_validator(mode="after")
    def _model_or_models(self) -> Team:
        if self.models and self.model:
            raise ValueError(f"team {self.name}: set either model or models, not both")
        return self


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


class ScriptedEvent(_Strict):
    """A script the engine runs once at the start of the run, in every team container, after setup
    and before any agent starts, as a scripted participant: a non-agent user that runs no other
    processes and has no home, so messages to it go nowhere. It is opt-in (``advanced.events``) and
    is always reported in the run's status and the judge report, so it is obvious whether a run used
    one."""

    name: str
    """A short slug, shown in status.json and the report (e.g. ``planted-exploit``)."""
    as_user: str
    """The participant's Linux user name. Must not be any agent's, service's or existing account's."""
    run: str
    """The script, a path inside the scenario folder (e.g. ``events/planted_exploit/plant.py``).
    Its whole folder is copied into the team image, readable only by the participant."""
    timeout: int = 900
    """The script and everything it starts are killed after this long."""
    note: str | None = None
    """One or two sentences for the judge on what the event does and how to read the run."""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,31}", v):
            raise ValueError("event names are lowercase letters, digits and dashes (max 32)")
        return v

    @field_validator("as_user")
    @classmethod
    def _user(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", v):
            raise ValueError("as_user must be a plain Linux user name")
        return v

    @field_validator("run")
    @classmethod
    def _run(cls, v: str) -> str:
        parts = Path(v).parts
        # The script lives under events/<name>/, which is NEVER one of the agent-visible source
        # trees (workspace, protected, board, history), so its payload is only ever baked in
        # readable by the participant, not copied somewhere agents can read it.
        if v.startswith("/") or ".." in parts:
            raise ValueError("run must be a path inside the scenario folder")
        if len(parts) < 3 or parts[0] != "events":
            raise ValueError("run must be events/<name>/<script> (e.g. events/planted_exploit/plant.py)")
        return v

    @field_validator("timeout", mode="before")
    @classmethod
    def _seconds(cls, v: Any) -> int:
        seconds = parse_duration(v)
        if seconds <= 0:
            raise ValueError("must be a positive duration")
        return seconds


TOOL_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


class MessageTool(_Strict):
    """What one direct-message tool is called and how it is described to agents."""

    name: str
    description: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not TOOL_NAME.fullmatch(v):
            raise ValueError("tool names are lowercase identifiers (letters, digits, _)")
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a tool needs a description")
        return v


class DirectMessages(_Strict):
    """How direct messages work for agents. The defaults are swarmbench's usual tools; a scenario
    replicating another setup can match its names, descriptions and behavior."""

    send: MessageTool | None = None
    """Name and description of the send tool (default ``send_message``)."""
    read: MessageTool | None = None
    """Name and description of the read tool (default ``check_messages``)."""
    read_all: bool = False
    """The read tool returns every direct message received so far (newest last), not only new ones."""
    list_users: bool = True
    """Offer ``list_users``. Without it, agents learn who is here from the prompt ({users})."""
    broadcast: bool = True
    """``to: "all"`` messages everyone at once. Off: messages go to one colleague at a time."""
    wake_preview: bool = True
    """When new messages wake an agent that ended its turn, the wake note quotes the start of each.
    Off: the note only says that there are new messages (and board posts) and where to read them."""


class CommandTool(_Strict):
    """A scenario command offered as an agent's own tool (Antigravity, with
    ``antigravity_native_tools``). The tool's arguments go to the command as one JSON object on
    standard input; its output is the tool's result."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    """JSON Schema of the arguments, as the model sees it. The command must check them itself."""
    command: list[str]
    """argv, run as the agent; the first item is an absolute path in the container."""
    timeout: int = 120

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not TOOL_NAME.fullmatch(v):
            raise ValueError("tool names are lowercase identifiers (letters, digits, _)")
        return v

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a tool needs a description")
        return v

    @field_validator("parameters")
    @classmethod
    def _parameters(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") != "object" or not isinstance(v.get("properties", {}), dict):
            raise ValueError("parameters must be a JSON Schema object with properties")
        return v

    @field_validator("command")
    @classmethod
    def _command(cls, v: list[str]) -> list[str]:
        if not v or not v[0].startswith("/"):
            raise ValueError("command is an argv list starting with an absolute path")
        return v

    @field_validator("timeout", mode="before")
    @classmethod
    def _timeout(cls, v: Any) -> int:
        return parse_duration(v)


class Advanced(_Strict):
    """Rarely needed overrides. Example scenarios should not need this block."""

    sandbox_image: str | None = None
    """The image team containers are built on, in place of the standard base image: a path to a
    Dockerfile in the scenario folder (its file name must contain "Dockerfile"), built on the
    base image, which it gets as the build argument BASE_IMAGE (``ARG BASE_IMAGE``, and a final
    stage ``FROM ${BASE_IMAGE}``; earlier stages, such as slow downloads, can start from a fixed
    image so they stay cached when the base changes), with the Dockerfile's folder as the build
    context; or the tag of an image already built that way. Each subfolder of that folder with
    its own ``Dockerfile`` (say ``lean/``) is a prebuilt stage: built first and tagged by a hash
    of its files, so it survives the build cache being cleared, and passed to the main Dockerfile
    as the build argument ``LEAN_IMAGE`` (``ARG LEAN_IMAGE`` / ``FROM ${LEAN_IMAGE} AS lean``)."""
    runtime: str | None = None
    """Docker runtime, e.g. ``runsc`` for gVisor on Linux hosts."""
    memory_per_agent_mb: int | None = None
    """Container memory is this times the team's agent count. None: a default per harness."""
    memory_shared_mb: int = 0
    """Extra memory per container, shared by all its agents: e.g. a large library that every
    compile maps into memory once, whatever the number of agents."""
    cpus: float | None = None
    """CPUs for each team container. None: scales with agent count."""
    hostname: str | None = None
    """Hostname for team containers (realism: no 'agent' or 'sandbox' in names). None: a default."""
    antigravity_native_tools: bool = False
    """Antigravity agents get direct messages (and ``command_tools``) as their own tools instead of
    through the SDK's generic MCP wrapper, where they are easy to miss. Off by default; a run that
    sets it says so in its settings."""
    direct_messages: DirectMessages = Field(default_factory=DirectMessages)
    command_tools: list[CommandTool] = Field(default_factory=list)
    """Scenario commands offered as agents' own tools. Needs the Antigravity harness with
    ``antigravity_native_tools`` (other harnesses would not get them)."""
    username_pattern: str = "u{n:02d}"
    """Linux user name for agent n."""
    monitor_model: str | None = None
    """Small model used to score ambiguous tool calls (None disables model scoring)."""
    monitor_stop_on: Literal["critical", "high", "never"] = "critical"
    judge_model: str | None = None
    """The judge model for every judging role (default: Opus 5.5)."""
    judge_fallback_model: str | None = None
    """Cheaper reader for the parts of a run with no warning signs, and for condensing notes on very
    large runs; it reads, never judges (default: Haiku 5.5)."""
    judge_fallback_reads_quiet: bool = True
    """The fallback reads every part with no warning signs (True), or only when the judge's cost
    cap forces it (False: the main judge model reads everything it can afford)."""
    judge_blocked_model: str | None = None
    """A model from another provider that answers a judge call the judge model's provider stopped
    with its safety filter (default: GPT-6.1 Sol; "none" turns it off)."""
    judge_max_cost: float | None = None
    """Hard dollar cap on judging each sample (epoch). None: the costs.judge_allowance of
    max_cost, or $10 when the scenario has no max_cost."""
    scanners: list[str] | None = None
    """Names of judge scanners to run (None means the default set)."""
    compaction: bool = True
    events: list[ScriptedEvent] = Field(default_factory=list)
    """Scripted events run at the start (see ScriptedEvent). Most scenarios have none."""
    extra: dict[str, Any] = Field(default_factory=dict)
    """Free-form settings for scenario-specific engine hooks."""


class Service(_Strict):
    """A program the scenario runs in the background in each team container, as its own user.

    Its folder ``services/<name>/`` is copied into the image readable only by that user.
    Agents reach it through a socket at ``/run/services/<name>.sock``."""

    name: str
    command: str
    """Program to start, relative to ``services/<name>/`` (e.g. ``server.py``)."""
    execution: Literal["python-tests"] | None = None
    """Opt in to isolated host-brokered Python test jobs; no Docker access in the service."""

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,23}", v):
            raise ValueError("service names are lowercase letters, digits and dashes (max 24)")
        return v

    @field_validator("command")
    @classmethod
    def _command(cls, v: str) -> str:
        if v.startswith("/") or ".." in Path(v).parts:
            raise ValueError("command must be a path inside the service's folder")
        return v


class Scenario(_Strict):
    name: str
    description: str = ""
    prompt: str = "prompt.md"
    system_prompt: str | None = None
    """Optional file whose text is added to every agent's system prompt (before its role's), e.g.
    rules a replicated setup gave as system instructions. ``prompt`` is the first user message."""
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
    services: list[Service] = Field(default_factory=list)
    """Background programs (see Service). Most scenarios have none."""

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
        self._validate_events()
        self._validate_tools()
        return self

    def _validate_tools(self) -> None:
        adv = self.advanced
        dm = adv.direct_messages
        names = [t.name for t in adv.command_tools]
        names += [dm.send.name if dm.send else "send_message", dm.read.name if dm.read else "check_messages"]
        if dm.list_users:
            names.append("list_users")
        if len(set(names)) != len(names):
            raise ValueError("advanced: command_tools and direct-message tools need distinct names")
        if adv.command_tools:
            if not adv.antigravity_native_tools:
                raise ValueError("advanced.command_tools needs advanced.antigravity_native_tools")
            others = sorted({t.harness for t in self.resolved_teams()} - {"antigravity"})
            if others:
                raise ValueError(
                    f"advanced.command_tools needs the antigravity harness (not {', '.join(others)})"
                )

    def _validate_events(self) -> None:
        events = self.advanced.events
        if not events:
            return
        names = [e.name for e in events]
        if len(set(names)) != len(names):
            raise ValueError("advanced.events: event names must be unique")
        # lazily: the engine's account names depend on this module
        from swarmbench.engine.image import BASE_ACCOUNTS, SYSTEM_ACCOUNTS
        from swarmbench.engine.layout import OPS_USER, team_users

        agents = {u.user for i in range(len(self.resolved_teams())) for u in team_users(self, i)}
        services = {s.name for s in self.services}
        # The event's top folder ("events") must not also be an agent-visible source tree, or its
        # payload would be copied somewhere agents can read it (e.g. /opt is world-readable),
        # defeating the private per-participant copy.
        public_roots = {"board", "history", "protected"}  # "protected" is the default even when unset
        for root in [self.protected, self.workspace, *(t.workspace for t in self.resolved_teams())]:
            if root:
                public_roots.add(Path(root).parts[0])
        for e in events:
            if e.as_user in agents:
                raise ValueError(f"advanced.events {e.name}: as_user {e.as_user} is an agent's user name")
            if e.as_user in services:
                raise ValueError(f"advanced.events {e.name}: as_user {e.as_user} is a service's user name")
            if e.as_user in BASE_ACCOUNTS | SYSTEM_ACCOUNTS | {OPS_USER}:
                raise ValueError(f"advanced.events {e.name}: as_user {e.as_user} is already an account")
            top = Path(e.run).parts[0]
            if top in public_roots:
                raise ValueError(
                    f"advanced.events {e.name}: run {e.run} is under {top}/, which agents can see; "
                    "put event scripts under their own events/ folder"
                )

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
            # a team's own model or models replace the shared ones; otherwise it inherits them
            if t.models or t.model:
                models = t.models or []
                model = t.models[0] if t.models else t.model
            else:
                models = base.models or []
                model = base.models[0] if base.models else base.model
            out.append(
                ResolvedTeam(
                    name=t.name,
                    agents=t.agents or base.agents,
                    model=model,
                    models=models,
                    effort=t.effort or base.effort,
                    harness=t.harness or base.harness,
                    token_budget=t.token_budget or base.token_budget,
                    messaging=messaging,
                    delivery=t.delivery or base.delivery,
                    roles=(t.roles if t.roles is not None else base.roles) or [],
                    prompt=t.prompt or self.prompt,
                    workspace=t.workspace if t.workspace is not None else self.workspace,
                    multi_team=multi,
                )
            )
        return out

    def agent_models(self) -> list[str]:
        """Every model an agent runs, each once, in order of first use."""
        return list(dict.fromkeys(m for t in self.resolved_teams() for m in t.agent_models()))

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
    """The team's model, or the first of ``models`` when it mixes models."""
    models: list[str] = Field(default_factory=list)
    effort: Effort | None
    harness: Harness
    token_budget: int
    messaging: Messaging
    delivery: Delivery | None
    roles: list[Role] = Field(default_factory=list)
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

    def role_for(self, index: int) -> Role | None:
        """The role of the team's agent number ``index`` (from 0), if the team has roles."""
        return self.roles[index % len(self.roles)] if self.roles else None

    def model_for(self, index: int) -> str:
        """The model of the team's agent number ``index`` (from 0)."""
        return self.models[index % len(self.models)] if self.models else self.model

    def agent_models(self) -> list[str]:
        """Each agent's model, in agent order."""
        return [self.model_for(i) for i in range(self.agents)]


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
            # a model given on the command line replaces a mix of models, and the other way round
            if key in ("swarm.model", "swarm.models") and isinstance(data.get("swarm"), dict):
                data["swarm"].pop("models" if key == "swarm.model" else "model", None)
            _set_dotted(data, key, value)
    swarm = data.get("swarm")
    if isinstance(swarm, dict) and swarm.get("model") and swarm.get("models"):
        raise ValueError(f"{file}: swarm sets both model and models; keep one")

    scenario = Scenario.model_validate(data)
    scenario.root = file.parent.resolve()
    return scenario


def file_team_models(team: dict[str, Any], swarm: dict[str, Any]) -> list[str]:
    """A team's models as written in a scenario file (a run's saved copy, say), without validating it."""
    if team.get("models") or team.get("model"):
        return list(team.get("models") or [team["model"]])
    return list(swarm.get("models") or ([swarm["model"]] if swarm.get("model") else []))


def dump_scenario(scenario: Scenario) -> str:
    """The resolved scenario as YAML (used to record exactly what was run)."""
    data = scenario.model_dump(mode="json", exclude_none=True)
    if data.get("swarm", {}).get("models"):
        data["swarm"].pop("model", None)  # the list replaces it, and a file may not set both
    return yaml.safe_dump(data, sort_keys=False)
