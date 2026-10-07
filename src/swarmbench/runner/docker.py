"""Find and remove a run's Docker containers, volumes and networks.

Every container the engine starts carries the label ``swarmbench.run=<run id>``. Volumes
and networks are found through that label too, and through the Compose project of the
labelled containers.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

RUN_LABEL = "swarmbench.run"
RUN_DIR_LABEL = "swarmbench.run_dir"
"""Absolute path of the run folder. Run ids are only unique within one runs folder, so this
label tells apart same-named runs from different checkouts."""
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
    run_dir: str | None = None
    """The run folder the resource was labelled with, if any."""

    def belongs_to(self, run_folder: Path) -> bool:
        """False only when the resource names a different run folder. An unlabelled resource
        is assumed to belong to the run its id names."""
        return self.run_dir is None or Path(self.run_dir) == run_folder.resolve()


def _list(kind: str, label_filter: str) -> list[Resource]:
    ident = "Name" if kind == "volume" else "ID"
    labels = [RUN_LABEL, PROJECT_LABEL, RUN_DIR_LABEL]
    fmt = "\t".join([f"{{{{.{ident}}}}}"] + [f'{{{{.Label "{label}"}}}}' for label in labels])
    cmd = {"container": ["ps", "-a"], "volume": ["volume", "ls"], "network": ["network", "ls"]}[kind]
    result = docker(*cmd, "--filter", f"label={label_filter}", "--format", fmt)
    if result.returncode != 0:
        return []
    out = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        name, run_id, project, run_dir = (line.split("\t") + ["", "", ""])[:4]
        out.append(Resource(kind, name, run_id or None, project or None, run_dir or None))
    return out


def labelled(run_id: str | None = None) -> list[Resource]:
    """Containers, volumes and networks labelled by swarmbench (for one run, or all)."""
    label = f"{RUN_LABEL}={run_id}" if run_id else RUN_LABEL
    found = _list("container", label) + _list("volume", label) + _list("network", label)
    # Volumes and networks created by Compose may only carry the project label.
    # They take their owner (run id and run folder) from the labelled resources of the project.
    projects = {r.project: r for r in found if r.project}
    seen = {(r.kind, r.id) for r in found}
    for project, owner in projects.items():
        for kind in ("volume", "network"):
            for r in _list(kind, f"{PROJECT_LABEL}={project}"):
                if (r.kind, r.id) not in seen:
                    r.run_id = r.run_id or owner.run_id
                    r.run_dir = r.run_dir or owner.run_dir
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


def remove_run(run_folder: Path, run_id: str, compose_project: str | None = None) -> list[str]:
    """Take down everything belonging to a run. Returns failures (empty when all went).

    Resources labelled with a different run folder (a same-named run from another checkout)
    are left alone.
    """
    projects = {compose_project} if compose_project else set()
    projects |= {r.project for r in labelled(run_id) if r.project and r.belongs_to(run_folder)}
    for project in projects:
        compose_down(project)
    return remove([r for r in labelled(run_id) if r.belongs_to(run_folder)])
