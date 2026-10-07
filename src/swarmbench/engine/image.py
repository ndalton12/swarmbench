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
from datetime import datetime, timedelta
from pathlib import Path

from swarmbench.config import Scenario
from swarmbench.design.dates import PLACEHOLDER
from swarmbench.design.history import seed_workspace

from .layout import OPS_USER, SEED_DIR, STAFF_GROUP, team_users
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


def _reject_links(folder: Path, root: Path) -> None:
    """``folder`` and every folder between it and the scenario ``root`` must be real folders."""
    current = folder
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {current}")
        current = current.parent


def _copy_tree(src: Path, dst: Path, root: Path) -> None:
    """Copy a scenario folder, refusing symlinks (they could point anywhere on the host)."""
    _reject_links(src, root)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {p}")
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)  # keeps the mode (executable checkers) and times


BOARD_AUTHOR_UID = 1600
BASE_ACCOUNTS = {"ops", "backupsvc", "tkovacs"}
"""Accounts that already exist in the base image."""
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _parse_post(text: str) -> tuple[dict[str, str], str]:
    """Optional front matter (``author:`` and ``date:``) and the post body."""
    m = _FRONT.match(text)
    if not m:
        return {}, text
    fields = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        if value.strip():
            fields[key.strip().lower()] = value.split("#")[0].strip()
    return fields, text[m.end() :]


def _seed_board(scenario: Scenario, dst: Path, now: datetime) -> list[str]:
    """Old posts for the board, as ``dst/<author>/<channel>/<unix-ms>-<author>.md``.

    Taken from an optional ``board/<channel>/*.md`` folder in the scenario. Each post
    may start with front matter giving its author (default ``ops``; created as a
    no-login account if needed) and its date as a run-relative offset such as
    ``-9d 08:12`` (default: spread over the previous two weeks). Dates in the text are
    rendered. Returns the authors. A ``general`` channel always exists.
    """
    (dst / OPS_USER / "general").mkdir(parents=True, exist_ok=True)
    src = scenario.path("board") if scenario.root else None
    authors = {OPS_USER}
    if src is None or not src.is_dir():
        return sorted(authors)
    agent_users = {u.user for i in range(len(scenario.resolved_teams())) for u in team_users(scenario, i)}
    _reject_links(src, scenario.root)  # type: ignore[arg-type]
    for channel in sorted(p for p in src.iterdir() if p.is_dir()):
        if channel.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {channel}")
        posts = sorted(p for p in channel.iterdir() if p.is_file() and not p.is_symlink())
        for i, post in enumerate(posts):
            fields, body = _parse_post(post.read_text())
            author = fields.get("author", OPS_USER)
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", author) or author in agent_users:
                raise ImageError(
                    f"{post}: author must be a plain user name that isn't an agent's: {author!r}"
                )
            if "date" in fields:
                when = datetime.fromisoformat(render_dates("{{date:" + fields["date"] + "|iso}}", now))
            else:
                when = now - timedelta(hours=(len(posts) - i) * 14 * 24 / (len(posts) + 1))
            ms = int(when.timestamp() * 1000)
            out = dst / author / channel.name / f"{ms}-{author}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render_dates(body, now).strip() + "\n")
            os.utime(out, (ms / 1000, ms / 1000))
            authors.add(author)
    return sorted(authors)


def _check_no_placeholders(ctx: Path) -> None:
    """Fail loudly if a ``{{date:...}}`` placeholder survived into anything agents will see."""
    leftovers = []
    for p in ctx.rglob("*"):
        if (
            p.is_file()
            and ".git" not in p.relative_to(ctx).parts
            and PLACEHOLDER.search(p.read_bytes().decode("utf-8", "replace"))
        ):
            leftovers.append(str(p.relative_to(ctx)))
    workspace = ctx / "seed" / "workspace"
    if (workspace / ".git").exists():
        history = subprocess.run(
            ["git", "-C", str(workspace), "log", "--all", "-p", "--format=%B"],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
        if PLACEHOLDER.search(history):
            leftovers.append("workspace history")
    if leftovers:
        raise ImageError(f"unrendered date placeholders in: {', '.join(sorted(leftovers))}")


def team_dockerfile(base: str, scenario: Scenario, team_index: int, authors: list[str]) -> str:
    users = team_users(scenario, team_index)
    lines = [f"FROM {base}", "RUN set -e \\"]
    for u in users:
        lines.append(
            f" && groupadd -g {u.uid} {u.user}"
            f" && useradd -M -d {u.home} -u {u.uid} -g {u.user} -G {STAFF_GROUP} -s /bin/bash {u.user}"
            f" && mkdir -p {u.home} && usermod -aG {u.user} root \\"
        )
    new_authors = [a for a in authors if a not in BASE_ACCOUNTS]
    for i, author in enumerate(new_authors):
        uid = BOARD_AUTHOR_UID + i
        lines.append(
            f" && groupadd -g {uid} {author}"
            f" && useradd -M -u {uid} -g {author} -G {STAFF_GROUP} -s /usr/sbin/nologin {author} \\"
        )
    lines.append(" && true")
    # Each author's posts are readable by that author (who copies them onto the board at
    # start, so the files are theirs) and by root through the group (to list channels).
    chowns = " && ".join(
        f"chown -R {a}:root {SEED_DIR}/board/{a} && chmod -R u=rwX,g=rX,o= {SEED_DIR}/board/{a}"
        for a in authors
    )
    lines += [
        f"COPY --chown=root:root seed/workspace/ {SEED_DIR}/workspace/",
        f"COPY --chown=root:root seed/board/ {SEED_DIR}/board/",
        "COPY --chown=root:root protected/ /opt/",
        (
            f"RUN chmod 711 {SEED_DIR} && chmod 700 {SEED_DIR}/workspace && chmod 755 {SEED_DIR}/board"
            f" && {chowns}"
            " && chmod -R a+rX,go-w /opt"
            # backdate seeded files: nothing should look created moments ago
            f" && find {SEED_DIR}/workspace /opt -newermt '-1 day' -exec touch -h -d '-4 days' {{}} +"
        ),
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
        now = now or datetime.now().astimezone()
        if team.workspace and scenario.root and scenario.path(team.workspace).is_dir():
            _reject_links(scenario.path(team.workspace), scenario.root)
            # backdated git history (history.yaml) and file times; never copies history files
            seed_workspace(scenario.root, team.workspace, ctx / "seed" / "workspace", now=now, seed=seed)
        authors = _seed_board(scenario, ctx / "seed" / "board", now)
        _check_no_placeholders(ctx)
        protected = scenario.protected_dir()
        if protected and protected.is_dir():
            _copy_tree(protected, ctx / "protected", scenario.root)  # type: ignore[arg-type]
        dockerfile = team_dockerfile(base, scenario, team_index, authors)
        (ctx / "Dockerfile").write_text(dockerfile)

        key = _hash_tree(ctx / "seed", ctx / "protected") + dockerfile
        tag = f"{TEAM_REPO}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"
        if not image_exists(tag):
            _docker_build(ctx, tag)
    return tag
