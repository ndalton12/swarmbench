"""Find and remove a run's Docker containers, volumes and networks.

Every container the engine starts carries the label ``swarmbench.run=<run id>``. Volumes
and networks are found through that label too, and through the Compose project of the
labelled containers.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

RUN_LABEL = "swarmbench.run"
PROJECT_LABEL = "com.docker.compose.project"


def docker(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    """Run a docker command and capture its output. A missing docker gives returncode 127."""
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return subprocess.CompletedProcess(["docker", *args], 127, "", "docker not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["docker", *args], 124, "", "docker timed out")


@dataclass
class Resource:
    kind: str
    """container, volume or network"""
    id: str
    run_id: str | None
    project: str | None


def _list(kind: str, label_filter: str) -> list[Resource]:
    fmt = f'{{{{.{"ID" if kind != "volume" else "Name"}}}}}\t{{{{.Label "{RUN_LABEL}"}}}}\t{{{{.Label "{PROJECT_LABEL}"}}}}'
    cmd = {"container": ["ps", "-a"], "volume": ["volume", "ls"], "network": ["network", "ls"]}[kind]
    result = docker(*cmd, "--filter", f"label={label_filter}", "--format", fmt)
    if result.returncode != 0:
        return []
    out = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        ident, run_id, project = (line.split("\t") + ["", ""])[:3]
        out.append(Resource(kind, ident, run_id or None, project or None))
    return out


def labelled(run_id: str | None = None) -> list[Resource]:
    """Containers, volumes and networks labelled by swarmbench (for one run, or all)."""
    label = f"{RUN_LABEL}={run_id}" if run_id else RUN_LABEL
    found = _list("container", label) + _list("volume", label) + _list("network", label)
    # Volumes and networks created by Compose may only carry the project label.
    projects = {r.project: r.run_id for r in found if r.project}
    seen = {(r.kind, r.id) for r in found}
    for project, owner in projects.items():
        for kind in ("volume", "network"):
            for r in _list(kind, f"{PROJECT_LABEL}={project}"):
                if (r.kind, r.id) not in seen:
                    r.run_id = r.run_id or owner
                    found.append(r)
                    seen.add((r.kind, r.id))
    return found


def compose_down(project: str) -> bool:
    """``docker compose -p <project> down``: stops and removes the project's containers."""
    return (
        docker(
            "compose", "-p", project, "down", "--volumes", "--remove-orphans", "--timeout", "10"
        ).returncode
        == 0
    )


def remove(resources: list[Resource]) -> list[str]:
    """Remove resources: containers first, then volumes and networks. Returns failures."""
    failures = []
    order = {"container": 0, "volume": 1, "network": 2}
    for r in sorted(resources, key=lambda r: order[r.kind]):
        args = {
            "container": ["rm", "-f", "-v"],
            "volume": ["volume", "rm", "-f"],
            "network": ["network", "rm"],
        }[r.kind]
        result = docker(*args, r.id)
        if result.returncode != 0 and "No such" not in result.stderr:
            failures.append(f"{r.kind} {r.id}: {result.stderr.strip()}")
    return failures


def remove_run(run_id: str, compose_project: str | None = None) -> list[str]:
    """Take down everything belonging to a run. Returns failures (empty when all went)."""
    projects = {compose_project} if compose_project else set()
    projects |= {r.project for r in labelled(run_id) if r.project}
    for project in projects:
        compose_down(project)
    return remove(labelled(run_id))
