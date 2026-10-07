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


def agent_infos(scenario: Scenario) -> list[AgentInfo]:
    """Every agent in the scenario (bridge ports are filled in once the agents start).

    ``advanced.extra["harnesses"]`` (a list, in agent order across the run) can give
    agents different harnesses within one team, e.g. ``[react, claude_code]``.
    """
    mixed = scenario.advanced.extra.get("harnesses")
    infos = []
    for index, team in enumerate(scenario.resolved_teams()):
        for u in team_users(scenario, index):
            harness = team.harness
            if isinstance(mixed, list) and len(infos) < len(mixed):
                harness = str(mixed[len(infos)])
            infos.append(
                AgentInfo(
                    name=u.agent,
                    team=team.name,
                    model=team.model,
                    harness=harness,
                    user=u.user,
                    uid=u.uid,
                    home=u.home,
                    sandbox=team_sandbox(team),
                )
            )
    return infos
