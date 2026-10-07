"""Docker images for team containers.

Two layers:

- the **base image** (``docker/Dockerfile``): tools, Python packages, the board
  command, the watcher, and the Claude Code and Codex binaries taken from
  inspect-swe's download cache (``download_agent_binary``);
- a small **team image** per scenario and team, built on the base: the agent
  users, the scenario's workspace and board seed (copied into the tmpfs work
  areas at start) and its protected files baked into /opt.

Baking the scenario into an image (rather than bind-mounting folders) keeps host
paths, scenario names and run ids out of the container's mount table.
"""

from __future__ import annotations

import hashlib
import os
import platform as host_platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

from swarmbench.config import Scenario

from .layout import OPS_UID, OPS_USER, SEED_DIR, STAFF_GROUP, team_users
from .text import render_dates

DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"
WATCHER_SOURCE = Path(__file__).resolve().parents[1] / "monitor" / "watcher.py"
BASE_REPO = "swarmbench-base"
TEAM_REPO = "swarmbench-team"


class ImageError(RuntimeError):
    pass


def docker_platform() -> str:
    """inspect-swe platform name for the Docker daemon's architecture."""
    try:
        arch = subprocess.run(
            ["docker", "info", "--format", "{{.Architecture}}"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        arch = host_platform.machine()
    return "linux-arm64" if arch in ("aarch64", "arm64") else "linux-x64"


def _cached_binaries(platform: str) -> tuple[Path, Path]:
    """Newest cached Claude Code binary and Codex package for ``platform``, downloading if needed."""
    from inspect_swe import cached_agent_binaries, download_agent_binary

    def newest(kind: str) -> Path | None:
        for b in cached_agent_binaries(kind, quiet=True):
            if b.path.name.endswith(platform) or b.path.name.endswith(f"{platform}.tar.gz"):
                return b.path
        return None

    claude = newest("claude_code")
    if claude is None:
        download_agent_binary("claude_code", "stable", platform)  # type: ignore[arg-type]
        claude = newest("claude_code")
    codex = newest("codex_cli")
    if codex is None or not codex.name.endswith(".tar.gz"):
        download_agent_binary("codex_cli", "latest", platform)  # type: ignore[arg-type]
        codex = newest("codex_cli")
    if claude is None or codex is None or not codex.name.endswith(".tar.gz"):
        raise ImageError(f"could not obtain Claude Code / Codex binaries for {platform}")
    return claude, codex


def _hash_tree(*paths: Path) -> str:
    h = hashlib.sha256()
    for root in paths:
        if root.is_file():
            h.update(root.name.encode())
            h.update(root.read_bytes())
            continue
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and "agents" not in p.relative_to(root).parts[:1]:
                h.update(str(p.relative_to(root)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()


def image_exists(tag: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0


def image_digest(tag: str) -> str | None:
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag], capture_output=True, text=True
    )
    return out.stdout.strip() or None


def _docker_build(context: Path, tag: str, dockerfile: Path | None = None) -> None:
    cmd = ["docker", "build", "-t", tag]
    if dockerfile is not None:
        cmd += ["-f", str(dockerfile)]
    cmd.append(str(context))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ImageError(f"docker build of {tag} failed:\n{result.stderr[-4000:]}")


def build_base_image(force: bool = False) -> str:
    """Build (or reuse) the base image and return its tag."""
    platform = docker_platform()
    claude, codex = _cached_binaries(platform)
    key = _hash_tree(DOCKER_DIR, WATCHER_SOURCE) + claude.name + codex.name
    tag = f"{BASE_REPO}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"
    if not force and image_exists(tag):
        return tag

    agents = DOCKER_DIR / "agents"
    agents.mkdir(exist_ok=True)
    if not (agents / "claude").exists() or (agents / "claude.version").read_text() != claude.name:
        shutil.copyfile(claude, agents / "claude")
        (agents / "claude.version").write_text(claude.name)
    if not (agents / "codex").exists() or (agents / "codex.version").read_text() != codex.name:
        target = agents / "codex"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        with tarfile.open(codex) as tar:
            tar.extractall(target, filter="tar")
        (agents / "codex.version").write_text(codex.name)

    sbin = DOCKER_DIR / "rootfs" / "usr" / "local" / "sbin"
    sbin.mkdir(parents=True, exist_ok=True)
    acctd = sbin / "acctd"
    if WATCHER_SOURCE.exists():
        shutil.copyfile(WATCHER_SOURCE, acctd)

    _docker_build(DOCKER_DIR, tag)
    return tag


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy a scenario folder, refusing symlinks (they could point anywhere on the host)."""
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {p}")
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)


def _seed_board(scenario: Scenario, dst: Path, now: datetime | None = None) -> None:
    """Old posts for the board, owned by the ``ops`` user.

    Taken from an optional ``board/<channel>/*.md`` folder in the scenario. Files
    named ``<unix-ms>-<anything>.md`` keep that time; others are spread over the
    previous days. A ``general`` channel always exists.
    """
    (dst / "general").mkdir(parents=True, exist_ok=True)
    src = scenario.path("board") if scenario.root else None
    if src is None or not src.is_dir():
        return
    now_ms = int(time.time() * 1000)
    for channel in sorted(p for p in src.iterdir() if p.is_dir()):
        posts = sorted(p for p in channel.iterdir() if p.is_file() and not p.is_symlink())
        for i, post in enumerate(posts):
            match = re.match(r"(\d{12,})-", post.name)
            ms = int(match.group(1)) if match else now_ms - (len(posts) - i) * 9 * 3600 * 1000
            out = dst / channel.name / f"{ms}-ops.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_dates(post.read_text(), now or datetime.now().astimezone()))
            os.utime(out, (ms / 1000, ms / 1000))


def _seed_workspace(
    scenario: Scenario, workspace: str, dest: Path, now: datetime | None, seed: str | None
) -> None:
    """Fill ``dest`` (empty) with the team's workspace.

    Uses the designer's ``seed_workspace`` when available: it replays the scenario's
    history.yaml as a backdated repository and backdates file times. Otherwise a plain copy.
    """
    try:
        from swarmbench.design.history import seed_workspace  # type: ignore[import-not-found]
    except ImportError:
        seed_workspace = None
    if seed_workspace is not None and scenario.root is not None:
        if seed_workspace(scenario.root, workspace, dest, now=now, seed=seed):
            return
    src = scenario.path(workspace)
    if src.is_dir():
        _copy_tree(src, dest)


def team_dockerfile(base: str, scenario: Scenario, team_index: int) -> str:
    users = team_users(scenario, team_index)
    lines = [f"FROM {base}", "RUN set -e \\"]
    for u in users:
        lines.append(
            f" && groupadd -g {u.uid} {u.user}"
            f" && useradd -M -d {u.home} -u {u.uid} -g {u.user} -G {STAFF_GROUP} -s /bin/bash {u.user}"
            f" && mkdir -p {u.home} && usermod -aG {u.user} root \\"
        )
    lines.append(" && true")
    lines += [
        f"COPY --chown=root:root seed/workspace/ {SEED_DIR}/workspace/",
        f"COPY --chown={OPS_UID}:{OPS_UID} seed/board/ {SEED_DIR}/board/",
        "COPY --chown=root:root protected/ /opt/",
        f"RUN chmod 711 {SEED_DIR} && chmod 700 {SEED_DIR}/workspace && chmod 750 {SEED_DIR}/board"
        f" && usermod -aG {OPS_USER} root"
        " && chmod -R a+rX,go-w /opt"
        # backdate seeded files: nothing should look created moments ago
        f" && find {SEED_DIR}/workspace /opt -newermt '-1 day' -exec touch -h -d '-4 days' {{}} +",
    ]
    return "\n".join(lines) + "\n"


def build_team_image(
    scenario: Scenario,
    team_index: int,
    base: str | None = None,
    now: datetime | None = None,
    seed: str | None = None,
) -> str:
    """Build (or reuse) the image for one team and return its tag.

    ``now`` (the run start) and ``seed`` (the run id) make the workspace history repeatable.
    """
    base = base or build_base_image()
    team = scenario.resolved_teams()[team_index]
    with tempfile.TemporaryDirectory(prefix="sb-team-") as tmp:
        ctx = Path(tmp)
        (ctx / "seed" / "workspace").mkdir(parents=True)
        (ctx / "seed" / "board").mkdir(parents=True)
        (ctx / "protected").mkdir()
        if team.workspace and scenario.root:
            _seed_workspace(scenario, team.workspace, ctx / "seed" / "workspace", now, seed)
        _seed_board(scenario, ctx / "seed" / "board", now)
        protected = scenario.protected_dir()
        if protected and protected.is_dir():
            _copy_tree(protected, ctx / "protected")
        dockerfile = team_dockerfile(base, scenario, team_index)
        (ctx / "Dockerfile").write_text(dockerfile)

        key = _hash_tree(ctx / "seed", ctx / "protected") + dockerfile
        tag = f"{TEAM_REPO}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"
        if not image_exists(tag):
            _docker_build(ctx, tag)
    return tag
