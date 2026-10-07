"""Compose file with one service (container) per team.

Containment comes from these settings: no network, every capability dropped
except SETUID/SETGID (Inspect's root helper needs them to start processes as an
agent's user), no-new-privileges, a read-only root filesystem, and CPU, memory
and process limits scaled by the number of agents.

Writable areas are tmpfs mounts, so no host path or volume name ever appears in
the container's mount table, and nothing is left behind after a run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from swarmbench.config import Scenario

from .layout import (
    BOARD,
    STAFF_GID,
    WATCHER_OUT_DIR,
    WORKSPACE,
    agent_infos,
    scenario_timezone,
    team_hostname,
    team_sandbox,
    team_users,
)

RUN_LABEL = "swarmbench.run"
RUN_DIR_LABEL = "swarmbench.run_dir"

MEMORY_BASE_MB = 1024
MEMORY_PER_AGENT_MB = {"react": 256, "claude_code": 1024, "codex_cli": 768}
PIDS_BASE = 256
PIDS_PER_AGENT = 256


def team_limits(scenario: Scenario, team_index: int) -> dict[str, Any]:
    team = scenario.resolved_teams()[team_index]
    agents = [a for a in agent_infos(scenario) if a.team == team.name]
    fixed = scenario.advanced.memory_per_agent_mb
    memory = MEMORY_BASE_MB + sum(fixed or MEMORY_PER_AGENT_MB[a.harness] for a in agents)
    cpus = scenario.advanced.cpus or min(2.0 + 0.5 * team.agents, 8.0)
    return {
        "mem_limit": f"{memory}m",
        "memswap_limit": f"{memory}m",
        "cpus": cpus,
        "pids_limit": PIDS_BASE + PIDS_PER_AGENT * team.agents,
    }


def team_service(
    scenario: Scenario, team_index: int, image: str, run_id: str, run_dir: str | None = None
) -> dict[str, Any]:
    tmpfs = [
        f"{WORKSPACE}:exec,mode=2775,uid=0,gid={STAFF_GID},size=2g",
        f"{BOARD}:mode=3775,uid=0,gid={STAFF_GID},size=64m",
        "/tmp:exec,mode=1777,size=2g",
        # Inspect keeps its tool binaries and service queues here, so it must allow exec
        "/var/tmp:exec,mode=1777,size=2g",
        f"{WATCHER_OUT_DIR}:mode=0700,uid=0,gid=0,size=256m",
        # workspace snapshots are built here before the host copies them out
        "/var/backups:mode=0700,uid=0,gid=0,size=512m",
    ]
    for u in team_users(scenario, team_index):
        tmpfs.append(f"{u.home}:exec,mode=0755,uid={u.uid},gid={u.uid},size=1g")

    service: dict[str, Any] = {
        "image": image,
        "x-local": True,
        "init": False,
        "command": ["/sbin/init"],
        "hostname": team_hostname(scenario, team_index),
        "working_dir": WORKSPACE,
        "environment": {"TZ": scenario_timezone(scenario)},
        "network_mode": "none",
        "read_only": True,
        "cap_drop": ["ALL"],
        "cap_add": ["SETUID", "SETGID"],
        "security_opt": ["no-new-privileges:true"],
        "tmpfs": tmpfs,
        "labels": {RUN_LABEL: run_id, **({RUN_DIR_LABEL: run_dir} if run_dir else {})},
        "stop_grace_period": "2s",
        **team_limits(scenario, team_index),
    }
    if scenario.advanced.runtime:
        service["runtime"] = scenario.advanced.runtime
    return service


def compose_config(
    scenario: Scenario, images: list[str], run_id: str, run_dir: str | None = None
) -> dict[str, Any]:
    services: dict[str, Any] = {}
    for index, team in enumerate(scenario.resolved_teams()):
        service = team_service(scenario, index, images[index], run_id, run_dir)
        if index == 0:
            service["x-default"] = True
        services[team_sandbox(team)] = service
    return {"services": services}


def write_compose(
    scenario: Scenario, images: list[str], run_id: str, path: Path, run_dir: str | None = None
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(compose_config(scenario, images, run_id, run_dir), sort_keys=False))
    return path
