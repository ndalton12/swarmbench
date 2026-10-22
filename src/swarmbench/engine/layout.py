"""Fixed paths inside team containers, and how agents map to Linux users.

Nothing an agent can see should mention swarmbench, agents, evaluations or
sandboxes, so the container-side names here are deliberately mundane.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from swarmbench.config import ResolvedTeam, Scenario
from swarmbench.types import AgentInfo

WORKSPACE = "/workspace"
BOARD = "/board"
PROTECTED = "/opt"
HOME_ROOT = "/home"
STAFF_GROUP = "staff"
STAFF_GID = 50  # Debian's existing "staff" group

WATCHER_PATH = "/usr/local/sbin/acctd"
"""The observer's container watcher (root, 0700)."""
WATCHER_OUT_DIR = "/var/log/acct"
"""Where the watcher writes its JSON lines (root, 0700, tmpfs)."""

RELAY_PATH = "/usr/local/sbin/svcgwd"
"""The bridge gateway that attributes each model request to the uid that made it (root, 0700)."""
RELAY_DIR = "/var/run/gw"
"""The gateway's config and request log (root, 0700, tmpfs)."""
RELAY_LOG = f"{RELAY_DIR}/requests.jsonl"
RELAY_PORT_OFFSET = 1000
"""Front port = bridge port + this. Non-root connections to a bridge port are redirected here."""


def front_port(bridge_port: int) -> int:
    return bridge_port + RELAY_PORT_OFFSET


SEED_DIR = "/var/lib/provision"
"""Pristine copies of the workspace (root only) and board posts (ops only), copied into the
tmpfs work areas at start. The folder itself is 0711, so agents cannot list it."""

UID_BASE = 2000
OPS_USER = "ops"
OPS_UID = 1500

SERVICE_DIR = "/srv"
"""Each background program's files, in ``/srv/<name>/`` (readable only by its own user)."""
SERVICE_STATE_DIR = "/var/lib/svc"
"""Each program's private writable folder, ``/var/lib/svc/<name>/`` (tmpfs, its user only)."""
SERVICE_SOCKETS = "/run/services"
"""Each program's socket is ``/run/services/<name>/<name>.sock``, in a folder only it can write."""
SVCRUN_PATH = "/usr/local/sbin/svcrun"
"""Keeps a background program running (engine/svcrun.py)."""
SERVICE_UID_BASE = 1700
"""Programs' users (each with its own group, same number): between board authors (1600+) and
agents (2000+)."""
PARTICIPANT_UID_BASE = 9000
"""Scripted participants (``advanced.events``) whose name isn't in the agents' numbering: well
above agents (2000+), services (1700+) and board authors (1600+), so it never collides with them."""
EVENT_DIR = "/var/lib/sched"
"""Each scripted participant's event files, baked into the image at ``/var/lib/sched/<user>/e<n>/``
(readable only by that user; the folder is 0700, so agents can't read or list it)."""

DEFAULT_HOSTNAMES = ["research-ws4", "rf-build02", "nlp-dev-03", "ml-batch07", "ws-gpu11", "dev-ana02"]


@dataclass(frozen=True)
class AgentUser:
    agent: str
    """Internal name (span name), e.g. ``agent-3``."""
    user: str
    uid: int
    home: str


def team_sandbox(team: ResolvedTeam) -> str:
    return f"team-{team.name}"


def team_hostname(scenario: Scenario, index: int) -> str:
    """advanced.extra["hostnames"] (one per team), else advanced.hostname, else a neutral default."""
    names = scenario.advanced.extra.get("hostnames")
    if isinstance(names, list) and index < len(names):
        return str(names[index])
    base = scenario.advanced.hostname
    if base:
        return base if index == 0 else f"{base}-{index + 1}"
    return DEFAULT_HOSTNAMES[index % len(DEFAULT_HOSTNAMES)]


def scenario_timezone(scenario: Scenario) -> str:
    """Container time zone: advanced.extra["timezone"], else history.yaml's, else UTC."""
    tz = scenario.advanced.extra.get("timezone")
    if not tz and scenario.root is not None and (scenario.root / "history.yaml").exists():
        data = yaml.safe_load((scenario.root / "history.yaml").read_text()) or {}
        tz = data.get("timezone")
    return str(tz or "UTC")


def team_offsets(scenario: Scenario) -> list[int]:
    """First user number for each team.

    With one team, users are u01, u02, ... With several teams, each team starts on
    the next multiple of ten, so the teams' user ranges never overlap (after an
    encounter, two different people called u01 would be confusing) and nothing in
    one team's numbering hints that another range exists.
    """
    offsets = []
    start = 1
    for team in scenario.resolved_teams():
        offsets.append(start)
        end = start + team.agents
        start = ((end - 1) // 10 + 1) * 10 + 1
    return offsets


def team_users(scenario: Scenario, team_index: int) -> list[AgentUser]:
    team = scenario.resolved_teams()[team_index]
    start = team_offsets(scenario)[team_index]
    pattern = scenario.advanced.username_pattern
    users = []
    for i, agent in enumerate(team.agent_names()):
        n = start + i
        user = pattern.format(n=n)
        users.append(AgentUser(agent=agent, user=user, uid=UID_BASE + n, home=f"{HOME_ROOT}/{user}"))
    return users


@dataclass(frozen=True)
class ServiceUser:
    name: str
    """The service's name, which is also its user name."""
    uid: int
    command: str

    @property
    def folder(self) -> str:
        return f"{SERVICE_DIR}/{self.name}"

    @property
    def state(self) -> str:
        return f"{SERVICE_STATE_DIR}/{self.name}"

    @property
    def socket_dir(self) -> str:
        return f"{SERVICE_SOCKETS}/{self.name}"

    @property
    def socket(self) -> str:
        return f"{self.socket_dir}/{self.name}.sock"


def service_users(scenario: Scenario) -> list[ServiceUser]:
    return [
        ServiceUser(name=s.name, uid=SERVICE_UID_BASE + i, command=s.command)
        for i, s in enumerate(scenario.services)
    ]


@dataclass(frozen=True)
class ParticipantUser:
    """A scripted participant: the non-agent user that runs a team's scheduled events."""

    user: str
    uid: int
    events: tuple[str, ...]
    """Names of the events it runs, in order; event n's files are in ``folder/e<n>/``."""

    @property
    def folder(self) -> str:
        return f"{EVENT_DIR}/{self.user}"

    def event_folder(self, event: str) -> str:
        return f"{self.folder}/e{self.events.index(event) + 1}"


def participant_users(scenario: Scenario) -> list[ParticipantUser]:
    """The scripted participants of ``advanced.events``, one per distinct ``as_user``.

    A name in the agents' numbering (``u31`` when agents are ``u01``-``u30``) gets the uid that
    numbering gives it, so it looks like the next participant; any other name gets one from
    PARTICIPANT_UID_BASE. The allocation avoids every agent and service uid, so participants never
    collide with them (board authors live at 1600+, well below both ranges).
    """
    agent_uids = {u.uid for i in range(len(scenario.resolved_teams())) for u in team_users(scenario, i)}
    service_uids = {s.uid for s in service_users(scenario)}
    pattern = scenario.advanced.username_pattern
    numbered = {pattern.format(n=n): UID_BASE + n for n in range(1, 1000)}
    out: list[ParticipantUser] = []
    used: set[int] = agent_uids | service_uids
    spare = PARTICIPANT_UID_BASE
    for user in dict.fromkeys(e.as_user for e in scenario.advanced.events):
        uid = numbered.get(user)
        if uid is None or uid in used:
            while spare in used:
                spare += 1
            uid = spare
        used.add(uid)
        events = tuple(e.name for e in scenario.advanced.events if e.as_user == user)
        out.append(ParticipantUser(user=user, uid=uid, events=events))
    return out


def agent_infos(scenario: Scenario) -> list[AgentInfo]:
    """Every agent in the scenario (bridge ports are filled in once the agents start).

    ``advanced.extra["harnesses"]`` (a list, in agent order across the run) can give
    agents different harnesses within one team, e.g. ``[react, claude_code]``.
    """
    mixed = scenario.advanced.extra.get("harnesses")
    infos = []
    for index, team in enumerate(scenario.resolved_teams()):
        for position, u in enumerate(team_users(scenario, index)):
            harness = team.harness
            role = team.role_for(position)
            if isinstance(mixed, list) and len(infos) < len(mixed):
                harness = str(mixed[len(infos)])
            infos.append(
                AgentInfo(
                    name=u.agent,
                    team=team.name,
                    model=team.model_for(position),
                    harness=harness,
                    user=u.user,
                    uid=u.uid,
                    home=u.home,
                    sandbox=team_sandbox(team),
                    role=role.name if role else None,
                )
            )
    return infos
