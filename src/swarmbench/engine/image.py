"""Docker images for team containers.

Two layers:

- the **base image** (``docker/Dockerfile``): tools, Python packages, the board
  command, the watcher, and the Claude Code and Codex binaries taken from
  inspect-swe's download cache (``download_agent_binary``);
- optionally a **scenario image** (``advanced.sandbox_image``): extra software a scenario
  needs, such as a theorem prover, built on the base from a Dockerfile in the scenario
  folder (or an image tag already built that way). Subfolders of the Dockerfile's folder
  that hold their own Dockerfile are *prebuilt stages*, built and tagged first so slow
  downloads survive Docker's build cache being cleared;
- a small **team image** per scenario and team, built on the base (or the scenario image): the agent
  users, the scenario's workspace and board seed (copied into the tmpfs work
  areas at start), its protected files baked into /opt, and its background programs
  (``services:``), each in ``/srv/<name>/`` owned by its own user and closed to everyone else.

Baking the scenario into an image (rather than bind-mounting folders) keeps host
paths, scenario names and run ids out of the container's mount table.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform as host_platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from swarmbench.config import Scenario
from swarmbench.design.dates import PLACEHOLDER
from swarmbench.design.history import seed_workspace

from .layout import (
    OPS_USER,
    SEED_DIR,
    SERVICE_DIR,
    STAFF_GROUP,
    SVCRUN_PATH,
    service_users,
    team_users,
)
from .text import render_dates

DOCKER_DIR = Path(__file__).resolve().parents[3] / "docker"
WATCHER_SOURCE = Path(__file__).resolve().parents[1] / "monitor" / "watcher.py"
SVCRUN_SOURCE = Path(__file__).resolve().parent / "svcrun.py"
BASE_REPO = "swarmbench-base"
SCENARIO_REPO = "swarmbench-scenario"
TEAM_REPO = "swarmbench-team"
BASE_ARG = "BASE_IMAGE"
"""Build argument that gives a scenario's Dockerfile the base image tag."""
SCENARIO_BUILD_LOCK = Path(tempfile.gettempdir()) / "swarmbench-scenario-build.lock"
"""Held while building scenario images and their prebuilt stages."""
_STAGE_NAME = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
"""Prebuilt stage folder names: they become part of an image name, which Docker keeps lowercase."""


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


def _docker_build(
    context: Path, tag: str, dockerfile: Path | None = None, build_args: dict[str, str] | None = None
) -> None:
    cmd = ["docker", "build", "-t", tag]
    if dockerfile is not None:
        cmd += ["-f", str(dockerfile)]
    for key, value in (build_args or {}).items():
        cmd += ["--build-arg", f"{key}={value}"]
    cmd.append(str(context))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise ImageError(f"docker build of {tag} failed:\n{result.stderr[-4000:]}")


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def build_base_image(force: bool = False) -> str:
    """Build (or reuse) the base image and return its tag.

    Preparing ``docker/agents/`` and building are guarded by a file lock, because
    experiments and screens start several runs at once and would otherwise race on
    the shared files (one process reading a version marker mid-rewrite by another).
    """
    import fcntl

    platform = docker_platform()
    claude, codex = _cached_binaries(platform)
    key = _hash_tree(DOCKER_DIR, WATCHER_SOURCE) + claude.name + codex.name
    tag = f"{BASE_REPO}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"
    if not force and image_exists(tag):
        return tag

    DOCKER_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = DOCKER_DIR / ".build.lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # another process may have built it while we waited for the lock
        if not force and image_exists(tag):
            return tag

        agents = DOCKER_DIR / "agents"
        agents.mkdir(exist_ok=True)
        if not (agents / "claude").exists() or _read_text(agents / "claude.version") != claude.name:
            shutil.copyfile(claude, agents / "claude")
            _write_atomic(agents / "claude.version", claude.name)
        if not (agents / "codex").exists() or _read_text(agents / "codex.version") != codex.name:
            target = agents / "codex"
            if target.exists():
                shutil.rmtree(target)
            target.mkdir()
            with tarfile.open(codex) as tar:
                tar.extractall(target, filter="tar")
            _write_atomic(agents / "codex.version", codex.name)

        sbin = DOCKER_DIR / "rootfs" / "usr" / "local" / "sbin"
        sbin.mkdir(parents=True, exist_ok=True)
        acctd = sbin / "acctd"
        if WATCHER_SOURCE.exists():
            shutil.copyfile(WATCHER_SOURCE, acctd)

        _docker_build(DOCKER_DIR, tag)
    return tag


def sandbox_dockerfile(scenario: Scenario) -> Path | None:
    """The scenario's own Dockerfile (``advanced.sandbox_image``), or None when there is none
    or the setting names an image tag. A path must stay inside the scenario folder."""
    spec = scenario.advanced.sandbox_image
    if not spec or scenario.root is None:
        return None
    candidate = scenario.root / spec
    looks_like_tag = ":" in spec or "@" in spec or "dockerfile" not in Path(spec).name.lower()
    if not candidate.exists() and looks_like_tag:
        return None  # an image tag
    root = scenario.root.resolve()
    if not candidate.resolve().is_relative_to(root):
        raise ImageError(f"advanced.sandbox_image {spec} is outside the scenario folder")
    if not candidate.is_file():
        raise ImageError(f"advanced.sandbox_image {spec} is missing")
    return candidate


def sandbox_image_problems(scenario: Scenario) -> list[str]:
    """What ``swarm check`` reports about ``advanced.sandbox_image`` without building anything."""
    try:
        dockerfile = sandbox_dockerfile(scenario)
    except ImageError as e:
        return [str(e)]
    if dockerfile is None:
        return []
    problems = []
    try:
        _reject_links(dockerfile.parent, scenario.root)  # type: ignore[arg-type]
        _check_no_links(dockerfile.parent)  # the prebuilt stages' folders too
    except ImageError as e:
        problems.append(str(e))
    froms = _from_lines(dockerfile)
    # the final stage is the image; earlier stages (e.g. downloads) may start from anything
    if not froms or not re.search(rf"\$\{{?{BASE_ARG}\b", froms[-1]):
        problems.append(
            f"{dockerfile.name} must build on the base image: declare `ARG {BASE_ARG}` and make "
            f"the final stage `FROM ${{{BASE_ARG}}}`"
        )
    args: dict[str, str] = {}
    for folder in prebuilt_stages(dockerfile.parent):
        where = f"prebuilt stage {folder.relative_to(dockerfile.parent)}/"
        if not _STAGE_NAME.fullmatch(folder.name):
            problems.append(f"{where}: folder name must be lowercase letters, digits and . _ - only")
        arg = stage_arg(folder.name)
        if arg == BASE_ARG or arg in args:
            problems.append(f"{where}: its build argument {arg} clashes with {args.get(arg, BASE_ARG)}")
        args[arg] = where
        if not _from_lines(folder / "Dockerfile"):
            problems.append(f"{where}: its Dockerfile has no FROM line")
    return problems


def _from_lines(dockerfile: Path) -> list[str]:
    try:
        text = dockerfile.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    return [line for line in text.splitlines() if line.strip().upper().startswith("FROM ")]


def prebuilt_stages(context: Path) -> list[Path]:
    """Immediate subfolders of a scenario image's folder that hold their own ``Dockerfile``.

    Each is built on its own first (its folder is the build context) and tagged by a hash of
    its files, and the main Dockerfile gets the tag as the build argument :func:`stage_arg`
    (``lean/`` gives ``LEAN_IMAGE``), to use as ``ARG LEAN_IMAGE`` / ``FROM ${LEAN_IMAGE} AS lean``
    / ``COPY --from=lean ...``. A tagged image survives ``docker image prune`` and the build
    cache being cleared, so slow downloads rerun only when that folder's own files change.
    """
    return sorted(
        p for p in context.iterdir() if p.is_dir() and not p.is_symlink() and (p / "Dockerfile").is_file()
    )


def stage_arg(name: str) -> str:
    """The build argument that passes a prebuilt stage's tag: ``lean`` -> ``LEAN_IMAGE``."""
    return re.sub(r"[^A-Za-z0-9]", "_", name).upper() + "_IMAGE"


def _hash_folder(h: hashlib._Hash, folder: Path) -> None:
    """Add every path under ``folder`` to ``h``: its kind and permission bits as well as its
    contents (an executable bit or an empty folder can change what a build does)."""
    for p in sorted(folder.rglob("*")):
        rel = str(p.relative_to(folder)).encode()
        mode = p.stat().st_mode
        h.update(len(rel).to_bytes(4, "big") + rel + mode.to_bytes(4, "big"))
        if p.is_file():
            data = p.read_bytes()
            h.update(len(data).to_bytes(8, "big") + data)


def _uses_base(dockerfile: Path) -> bool:
    """Whether a Dockerfile can see the base image tag: it declares ``ARG BASE_IMAGE`` (a RUN
    step may then read it from the environment) or refers to ``$BASE_IMAGE``."""
    pattern = rf"^\s*ARG\s+{BASE_ARG}\b|\$\{{?{BASE_ARG}\b"
    return re.search(pattern, _read_text(dockerfile), re.MULTILINE | re.IGNORECASE) is not None


def _prebuilt_tags(context: Path, base: str) -> dict[str, tuple[Path, str]]:
    """Build argument -> (stage folder, tag) for each prebuilt stage. A stage's tag depends on
    its own folder only, plus the base image if its Dockerfile mentions ``BASE_IMAGE``."""
    tags = {}
    for folder in prebuilt_stages(context):
        h = hashlib.sha256(f"{base if _uses_base(folder / 'Dockerfile') else ''}\0".encode())
        _hash_folder(h, folder)
        tags[stage_arg(folder.name)] = (folder, f"{SCENARIO_REPO}-{folder.name}:{h.hexdigest()[:12]}")
    return tags


def _check_no_links(folder: Path) -> None:
    for p in folder.rglob("*"):
        if p.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {p}")


def _layers(tag: str) -> list[str]:
    out = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{json .RootFS.Layers}}", tag],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise ImageError(f"image {tag} not found locally; build it or pull it first")
    return json.loads(out.stdout or "[]") or []


def build_scenario_image(scenario: Scenario, base: str, force: bool = False) -> str:
    """The image the scenario's team images build on: ``base``, or the scenario's own image
    (``advanced.sandbox_image``), built on ``base`` if it is a Dockerfile.

    A Dockerfile is built at most once per content: the tag is a hash of the base tag and the
    Dockerfile's folder, and a file lock stops parallel runs building it twice. Prebuilt stages
    (:func:`prebuilt_stages`) are built first, each reused while its own folder is unchanged.
    """
    spec = scenario.advanced.sandbox_image
    if not spec:
        return base
    dockerfile = sandbox_dockerfile(scenario)
    if dockerfile is None:
        _check_built_on(spec, base)
        return spec
    problems = sandbox_image_problems(scenario)
    if problems:
        raise ImageError("; ".join(problems))
    context = dockerfile.parent
    stages = _prebuilt_tags(context, base)
    h = hashlib.sha256(f"{base}\0{dockerfile.relative_to(context)}\0".encode())
    for arg, (_, stage_tag) in stages.items():
        h.update(f"{arg}={stage_tag}\0".encode())
    _hash_folder(h, context)  # includes the prebuilt stages' folders
    tag = f"{SCENARIO_REPO}:{h.hexdigest()[:12]}"
    if not force and image_exists(tag):
        _check_built_on(tag, base)
        return tag

    import fcntl

    # one lock for every checkout and worktree, since image tags are shared through the Docker
    # daemon: two worktrees must not both start a slow prebuilt stage
    with open(SCENARIO_BUILD_LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if force or not image_exists(tag):
            # ``force`` rebuilds the scenario image, never the slow prebuilt stages
            for folder, stage_tag in stages.values():
                if not image_exists(stage_tag):
                    stage_args = {BASE_ARG: base} if _uses_base(folder / "Dockerfile") else {}
                    _docker_build(folder, stage_tag, folder / "Dockerfile", build_args=stage_args)
            args = {BASE_ARG: base} | {arg: stage_tag for arg, (_, stage_tag) in stages.items()}
            _docker_build(context, tag, dockerfile, build_args=args)
    _check_built_on(tag, base)  # e.g. a multi-stage build whose last stage is not on the base
    return tag


def _check_built_on(tag: str, base: str) -> None:
    """The image must contain the base image's layers, or agents would lack its tools."""
    layers, base_layers = _layers(tag), _layers(base)
    if layers[: len(base_layers)] != base_layers:
        raise ImageError(
            f"advanced.sandbox_image {tag} was not built on the current base image {base}; "
            f"its Dockerfile's final stage must be FROM ${{{BASE_ARG}}} "
            f"(or rebuild the image with --build-arg {BASE_ARG}={base})"
        )


def _reject_links(folder: Path, root: Path) -> None:
    """``folder`` and every folder between it and the scenario ``root`` must be real folders."""
    current = folder
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {current}")
        current = current.parent


def omitted(rel: str, patterns: Sequence[str]) -> bool:
    """Whether ``rel`` (a path relative to the copied folder) is left out by ``patterns``: globs
    where ``*`` stays within one folder, ``!`` puts files back, and the last match decides."""
    out = False
    for pattern in patterns:
        keep = pattern.startswith("!")
        parts, globs = rel.split("/"), pattern.removeprefix("!").split("/")
        if len(parts) == len(globs) and all(
            fnmatch.fnmatchcase(a, g) for a, g in zip(parts, globs, strict=True)
        ):
            out = not keep
    return out


def omit_under(patterns: Sequence[str], folder: str | None) -> list[str]:
    """The ``advanced.omit`` patterns for files under ``folder`` (scenario-relative), relative to it."""
    if not folder:
        return []
    prefix = folder.strip("/") + "/"
    out = []
    for pattern in patterns:
        neg = "!" if pattern.startswith("!") else ""
        body = pattern.removeprefix("!")
        if body.startswith(prefix):
            out.append(neg + body[len(prefix) :])
    return out


def _copy_tree(src: Path, dst: Path, root: Path, omit: Sequence[str] = ()) -> None:
    """Copy a scenario folder, refusing symlinks (they could point anywhere on the host), without
    the files ``omit`` leaves out (see ``omitted``)."""
    _reject_links(src, root)
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if p.is_symlink():
            raise ImageError(f"scenario folder contains a symlink: {p}")
        if omit and not p.is_dir() and omitted(rel.as_posix(), omit):
            continue
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)  # keeps the mode (executable checkers) and times


BOARD_AUTHOR_UID = 1600
BASE_ACCOUNTS = {"ops", "backupsvc", "tkovacs"}
"""Accounts that already exist in the base image."""
SYSTEM_ACCOUNTS = {
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail", "news", "uucp",
    "proxy", "www-data", "backup", "list", "irc", "_apt", "nobody", "adm", "tty", "disk",
    "kmem", "dialout", "fax", "voice", "cdrom", "floppy", "tape", "sudo", "audio", "dip",
    "operator", "src", "shadow", "utmp", "video", "sasl", "plugdev", "staff", "users",
    "nogroup",
}  # fmt: skip
"""Debian's own users and groups, which a service can't be named."""


def service_problems(scenario: Scenario) -> list[str]:
    """Services whose folder or program is missing, or whose name is already an account name."""
    problems = []
    names = [svc.name for svc in scenario.services]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"service {name} is listed more than once")
    agents = {u.user for i in range(len(scenario.resolved_teams())) for u in team_users(scenario, i)}
    shared = (
        scenario.encounter.path if scenario.encounter and scenario.encounter.via == "shared_dir" else None
    )
    for svc in scenario.services:
        if svc.name in agents | BASE_ACCOUNTS | SYSTEM_ACCOUNTS:
            problems.append(f"service {svc.name}: the name is already a user on the machine")
        folder = f"{SERVICE_DIR}/{svc.name}"
        if shared and (shared == folder or shared.startswith(folder + "/")):
            problems.append(f"service {svc.name}: its folder {folder} is the encounter's shared folder")
        if scenario.root is None:
            continue
        folder = scenario.path(f"services/{svc.name}")
        if not folder.is_dir() or folder.is_symlink():
            problems.append(f"service {svc.name}: folder services/{svc.name}/ is missing")
        elif not (folder / svc.command).is_file():
            problems.append(f"service {svc.name}: program services/{svc.name}/{svc.command} is missing")
        elif not svc.command.endswith(".py") and not os.access(folder / svc.command, os.X_OK):
            problems.append(f"service {svc.name}: program {svc.command} is not executable")
    return problems


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
    from .events import participant_dockerfile_lines

    services = service_users(scenario)
    for svc in services:
        if svc.name in authors:
            raise ImageError(f"service {svc.name} has the same name as a board post author")
        # its own user and group, outside the staff group, so it can't write the shared areas
        lines.append(
            f" && groupadd -g {svc.uid} {svc.name}"
            f" && useradd -M -d {svc.state} -u {svc.uid} -g {svc.name} -s /usr/sbin/nologin {svc.name} \\"
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
    if services:
        lines += [f"COPY --chown=root:root svcrun.py {SVCRUN_PATH}", f"RUN chmod 755 {SVCRUN_PATH}"]
    for svc in services:
        # readable only by the program's own user
        lines += [
            f"COPY --chown={svc.name}:{svc.name} services/{svc.name}/ {svc.folder}/",
            (
                f"RUN chmod 700 {svc.folder} && chmod -R go-rwx {svc.folder}"
                f" && find {svc.folder} -newermt '-1 day' -exec touch -h -d '-4 days' {{}} +"
            ),
        ]
    from .layout import participant_users

    for p in participant_users(scenario):
        if p.user in authors:
            raise ImageError(f"scripted event participant {p.user} has the same name as a board post author")
    lines += participant_dockerfile_lines(scenario, team_index, STAFF_GROUP)
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
        (ctx / "services").mkdir()
        (ctx / "events").mkdir()
        now = now or datetime.now().astimezone()
        if team.workspace and scenario.root and scenario.path(team.workspace).is_dir():
            _reject_links(scenario.path(team.workspace), scenario.root)
            # backdated git history (history.yaml) and file times; never copies history files
            seed_workspace(
                scenario.root,
                team.workspace,
                ctx / "seed" / "workspace",
                now=now,
                seed=seed,
                omit=omit_under(scenario.advanced.omit, team.workspace),
            )
        authors = _seed_board(scenario, ctx / "seed" / "board", now)
        _check_no_placeholders(ctx)
        protected = scenario.protected_dir()
        if protected and protected.is_dir():
            omit = omit_under(scenario.advanced.omit, protected.relative_to(scenario.root).as_posix())  # type: ignore[arg-type]
            _copy_tree(protected, ctx / "protected", scenario.root, omit)  # type: ignore[arg-type]
        if scenario.services:
            problems = service_problems(scenario)
            if problems:
                raise ImageError("; ".join(problems))
            shutil.copyfile(SVCRUN_SOURCE, ctx / "svcrun.py")
            for svc in scenario.services:
                _copy_tree(scenario.path(f"services/{svc.name}"), ctx / "services" / svc.name, scenario.root)  # type: ignore[arg-type]
        if scenario.advanced.events:
            from .events import copy_event_trees, event_problems

            problems = event_problems(scenario)
            if problems:
                raise ImageError("; ".join(problems))
            copy_event_trees(scenario, team_index, ctx, _copy_tree)
        dockerfile = team_dockerfile(base, scenario, team_index, authors)
        (ctx / "Dockerfile").write_text(dockerfile)

        services = hashlib.sha256()
        _hash_folder(services, ctx / "services")  # with permission bits: they decide how a program starts
        _hash_folder(services, ctx / "events")  # the scripted-event files, with permission bits
        if (ctx / "svcrun.py").exists():
            services.update((ctx / "svcrun.py").read_bytes())
        key = _hash_tree(ctx / "seed", ctx / "protected") + services.hexdigest() + dockerfile
        key += image_digest(base) or ""
        tag = f"{TEAM_REPO}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"
        if not image_exists(tag):
            _docker_build(ctx, tag)
    return tag
