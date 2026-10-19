"""Warn before a launch when disk space is low.

A run that fills a disk fails badly: image builds and workspace snapshots break, and the
judge may be left without a record. Two disks matter. This computer's disk holds the runs
folder, and with Docker Desktop or Colima it also holds the virtual disk Docker writes into,
which grows as Docker uses it but doesn't shrink by itself. Docker's own disk is measured from
inside a throwaway container, so it works the same on Docker Desktop, Colima and Linux.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import docker

DOCKER_TIMEOUT = 15.0
"""Seconds allowed for each Docker call, so a slow or stuck Docker can't hold up a launch."""
LOW_GB = 10.0
"""Warn when either disk has less free space than this."""
CHECK_ENV = "SWARMBENCH_NO_DISK_CHECK"
"""Set to 1 to skip the check (tests do)."""
GB = 1_000_000_000


def host_free(path: Path) -> int | None:
    """Free bytes on the disk holding ``path`` (or its nearest existing parent)."""
    path = path.resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def docker_free() -> int | None:
    """Free bytes on Docker's disk, from ``df`` in a throwaway container started from the newest
    swarmbench image already on this machine (never pulled). None if there is no such image or
    Docker can't say."""
    images = docker.swarm_images(timeout=DOCKER_TIMEOUT)
    if not images:
        return None
    result = docker.docker(
        "run", "--rm", "--pull", "never", "--network", "none", "--entrypoint", "df",
        images[0].tag, "-Pk", "/",
        timeout=DOCKER_TIMEOUT,
    )  # fmt: skip
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().splitlines()
    try:
        return int(lines[-1].split()[3]) * 1024
    except (IndexError, ValueError):
        return None


def uses_colima() -> bool:
    result = docker.docker("info", "--format", "{{.Name}}", timeout=DOCKER_TIMEOUT)
    return result.returncode == 0 and result.stdout.strip().startswith("colima")


def warnings(runs_folder: Path, low_gb: float = LOW_GB) -> list[str]:
    """Plain-language warnings when a disk is low (empty when all is well or checking is off)."""
    if os.environ.get(CHECK_ENV):
        return []
    out = []
    host = host_free(runs_folder)
    if host is not None and host < low_gb * GB:
        out.append(f"Only {host / GB:.1f} GB free on this computer's disk.")
    inside = docker_free()
    if inside is not None and inside < low_gb * GB:
        out.append(f"Only {inside / GB:.1f} GB free on Docker's disk.")
    if not out:
        return []
    if inside is None:  # Docker didn't answer: don't wait on it again for the details
        out.append("`swarm cleanup` removes old swarmbench images.")
        return out
    from .control import images_to_prune

    prune, _ = images_to_prune(timeout=DOCKER_TIMEOUT)
    reclaimable = docker.reclaimable_images(timeout=DOCKER_TIMEOUT)
    hint = f"`swarm cleanup` can remove {len(prune)} old swarmbench image(s)"
    hint += f"; Docker counts {reclaimable} of images that no container uses." if reclaimable else "."
    out.append(hint)
    if host is not None and host < low_gb * GB and uses_colima():
        out.append(
            "Colima's disk doesn't shrink by itself: after cleaning up, `colima ssh -- sudo fstrim -av` "
            "gives the freed space back to this computer."
        )
    return out
