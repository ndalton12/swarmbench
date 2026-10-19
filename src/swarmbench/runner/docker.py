"""Find and remove a run's Docker containers, volumes and networks.

Every container the engine starts carries the label ``swarmbench.run=<run id>``. Volumes
and networks are found through that label too, and through the Compose project of the
labelled containers.

Old images can be pruned too, but only those swarmbench builds itself (see
:func:`is_swarm_repo`).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
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


# ---- images ---------------------------------------------------------------------------

TEAM_IMAGE_REPO = "swarmbench-team"
"""Images the engine builds per scenario and team."""
BASE_IMAGE_REPO = "swarmbench-base"
"""The standard image every team image is built on."""
SCENARIO_IMAGE_REPO = "swarmbench-scenario"
"""Scenario images (``advanced.sandbox_image``) built on the base. Their prebuilt stages are
``swarmbench-scenario-<folder>``, e.g. ``swarmbench-scenario-lean``."""


def is_stage_repo(repo: str) -> bool:
    """Prebuilt scenario-image stages (e.g. the Lean toolchain): slow to rebuild, and other
    checkouts may need older ones, so cleanup never removes them."""
    return repo.startswith(f"{SCENARIO_IMAGE_REPO}-")


def is_swarm_repo(repo: str) -> bool:
    """Whether images in this repository are built by swarmbench. Only these are ever pruned."""
    return repo in (TEAM_IMAGE_REPO, BASE_IMAGE_REPO, SCENARIO_IMAGE_REPO) or repo.startswith(
        f"{SCENARIO_IMAGE_REPO}-"
    )


@dataclass
class Image:
    tag: str
    """``<repo>:<tag>``, e.g. ``swarmbench-team:<hash>``"""
    id: str
    created: datetime

    @property
    def repo(self) -> str:
        return self.tag.rsplit(":", 1)[0]


def swarm_images(timeout: float = 120) -> list[Image]:
    """Tagged images built by swarmbench (team, base, scenario and prebuilt-stage images),
    newest first."""
    fmt = "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}"
    result = docker("images", "--format", fmt, timeout=timeout)
    if result.returncode != 0:
        return []
    out = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not is_swarm_repo(parts[0]) or parts[1] == "<none>":
            continue
        try:
            created = datetime.strptime(parts[3][:25], "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            continue
        out.append(Image(f"{parts[0]}:{parts[1]}", parts[2], created))
    return sorted(out, key=lambda i: i.created, reverse=True)


def team_images() -> list[Image]:
    """Tagged swarmbench-team images, newest first."""
    return [i for i in swarm_images() if i.repo == TEAM_IMAGE_REPO]


def short_id(image_id: str) -> str:
    """The 12-character form of an image id, with or without its ``sha256:`` prefix."""
    return image_id.removeprefix("sha256:")[:12]


def image_layers(refs: list[str], timeout: float = 120) -> dict[str, tuple[str, ...]] | None:
    """Layer digests of images (tags or ids), keyed by short image id. None if Docker
    couldn't inspect them all, so callers can be careful rather than guess."""
    if not refs:
        return {}
    fmt = "{{.Id}}\t{{json .RootFS.Layers}}"
    result = docker("image", "inspect", "--format", fmt, *sorted(set(refs)), timeout=timeout)
    if result.returncode != 0:
        return None
    out: dict[str, tuple[str, ...]] = {}
    for line in result.stdout.splitlines():
        image_id, _, layers = line.partition("\t")
        try:
            out[short_id(image_id)] = tuple(json.loads(layers) or ())
        except ValueError:
            return None
    return out


def images_used_by_containers(timeout: float = 120) -> set[str] | None:
    """Image names and ids of every container on this machine, running or stopped. None if
    Docker couldn't list them, so callers can leave images alone rather than guess.

    ``docker ps`` can't format a container's image id, so this inspects the containers."""
    listed = docker("ps", "-aq", "--no-trunc", timeout=timeout)
    if listed.returncode != 0:
        return None
    ids = listed.stdout.split()
    if not ids:
        return set()
    result = docker(
        "container", "inspect", "--format", "{{.Image}}\t{{.Config.Image}}", *ids, timeout=timeout
    )
    if result.returncode != 0:
        # a container removed between the two calls makes inspect fail: list again once
        listed = docker("ps", "-aq", "--no-trunc", timeout=timeout)
        ids = listed.stdout.split() if listed.returncode == 0 else None
        if ids is None:
            return None
        if not ids:
            return set()
        result = docker(
            "container", "inspect", "--format", "{{.Image}}\t{{.Config.Image}}", *ids, timeout=timeout
        )
        if result.returncode != 0:
            return None
    used: set[str] = set()
    for line in result.stdout.splitlines():
        used.update(part for part in line.split("\t") if part)
    return used


def reclaimable_images(timeout: float = 120) -> str | None:
    """Docker's own figure for the disk used by images no container uses, e.g. ``39.95GB
    (59%)``. None if Docker can't say."""
    result = docker("system", "df", "--format", "{{.Type}}\t{{.Reclaimable}}", timeout=timeout)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        kind, _, amount = line.partition("\t")
        if kind == "Images":
            return amount.strip() or None
    return None


def remove_image(tag: str) -> str | None:
    """Untag and remove one swarmbench image (never forced). Returns an error message or None.

    Docker deletes only the layers no other image uses, and refuses an image a container
    uses."""
    repo = tag.rsplit(":", 1)[0] if ":" in tag else ""
    if not is_swarm_repo(repo):
        return f"{tag}: not a swarmbench image"
    result = docker("rmi", tag)
    return None if result.returncode == 0 else f"{tag}: {result.stderr.strip()}"
