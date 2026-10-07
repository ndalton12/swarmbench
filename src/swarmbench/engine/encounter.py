"""Encounters: the moment separate teams can find each other.

Nothing is shared between team containers before the encounter. When it opens
(``encounter.after`` seconds into the run), the host starts relaying:

- ``shared_dir``: a folder (``encounter.path``) is merged two ways between the
  containers every few seconds, like a network share that starts working. Files
  keep their names and times; on a conflict the newer file wins; deletions are not
  relayed. Copies arrive owned by root (containers can't change file owners), and
  the real author is recorded in ``swarm.encounter_sync`` events.
- ``board_channel``: a board channel (``encounter.path``) appears on every team's
  board, and posts are mirrored between them. A mirrored post is a root-owned file
  named ``<unix-ms>-<user>@<host>.md``, which the board command shows as written by
  ``user@host``. Agents can't create root-owned files, so they can't forge these.
- ``file``: ``encounter.source`` from the scenario folder is copied into every
  team's workspace at ``encounter.path``.

Every write into a container goes through ``_WRITE``: it walks the destination
path one component at a time with ``O_NOFOLLOW``, writes a temporary file in the
destination folder and renames it into place, so symlinks planted by agents can't
redirect it anywhere.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import TYPE_CHECKING, Any

import anyio
from inspect_ai.log import transcript

from .layout import BOARD, OPS_USER, WORKSPACE
from .text import render_dates


def add_problem(text: str) -> None:
    from .orchestrator import add_problem as _add

    _add(text)


if TYPE_CHECKING:
    from .orchestrator import Swarm, TeamRuntime

PYTHON = "/usr/local/bin/python3"
SYNC_SECONDS = 3.0
DRY_RUN_ENCOUNTER_AFTER = 10.0
MAX_FILE = 5 * 1024 * 1024
MAX_FILES = 2000

# Lists regular files under a folder (no symlinks followed), with metadata and a digest.
_LIST = r"""
import hashlib, json, os, stat, sys
root = sys.argv[1]
out = {}
def walk(dfd, rel):
    for name in sorted(os.listdir(dfd)):
        if name.startswith(".sync-"):
            continue
        try:
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        except OSError:
            continue
        path = rel + name
        if stat.S_ISDIR(st.st_mode):
            try:
                sub = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dfd)
            except OSError:
                continue
            try:
                walk(sub, path + "/")
            finally:
                os.close(sub)
        elif stat.S_ISREG(st.st_mode) and st.st_size <= %(max)d and len(out) < %(files)d:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                with os.fdopen(fd, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            out[path] = {"mtime": st.st_mtime, "uid": st.st_uid, "size": st.st_size,
                         "sha": hashlib.sha256(data).hexdigest()}
try:
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    for part in [p for p in root.split("/") if p]:
        nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        os.close(fd)
        fd = nxt
    walk(fd, "")
except OSError:
    pass
print(json.dumps(out))
""" % {"max": MAX_FILE, "files": MAX_FILES}

# Reads the requested files (relative paths, no symlinks followed) as base64.
_READ = r"""
import base64, json, os, sys
root = sys.argv[1]
want = json.loads(sys.stdin.read())
out = {}
for rel in want:
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        parts = [p for p in (root + "/" + rel).split("/") if p]
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        f = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        os.close(fd)
        with os.fdopen(f, "rb") as fh:
            out[rel] = base64.b64encode(fh.read(%(max)d)).decode()
    except OSError:
        pass
print(json.dumps(out))
""" % {"max": MAX_FILE}

# Writes files below a root folder without following symlinks (see module docstring).
_WRITE = r"""
import base64, json, os, secrets, sys
root = sys.argv[1]
files = json.loads(sys.stdin.read())
done, failed = [], []
def opendir(parts, create):
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    for part in parts:
        try:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            if not create:
                raise
            os.mkdir(part, 0o2775, dir_fd=fd)
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.fchmod(nxt, 0o2775)
        os.close(fd)
        fd = nxt
    return fd
root_parts = [p for p in root.split("/") if p]
for item in files:
    parts = [p for p in item["rel"].split("/") if p and p not in (".", "..")]
    try:
        dfd = opendir(root_parts + parts[:-1], True)
        tmp = ".sync-" + secrets.token_hex(6)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(item["data"]))
            os.fchmod(f.fileno(), int(item.get("mode", 0o664)))
            if item.get("mtime"):
                os.utime(f.fileno(), (item["mtime"], item["mtime"]))
        os.rename(tmp, parts[-1], src_dir_fd=dfd, dst_dir_fd=dfd)
        os.close(dfd)
        done.append(item["rel"])
    except OSError as ex:
        failed.append([item["rel"], str(ex)])
if not files:
    os.close(opendir(root_parts, True))  # just make sure the folder exists
print(json.dumps({"done": done, "failed": failed}))
"""


async def _py(rt: TeamRuntime, script: str, args: list[str], stdin: Any = None) -> Any:
    assert rt.sandbox is not None
    result = await rt.sandbox.exec(
        [PYTHON, "-I", "-c", script, *args],
        input=json.dumps(stdin) if stdin is not None else None,
        user="root",
        timeout=120,
    )
    if not result.success:
        raise RuntimeError(result.stderr.strip()[-500:])
    return json.loads(result.stdout)


async def list_files(rt: TeamRuntime, root: str) -> dict[str, dict[str, Any]]:
    return await _py(rt, _LIST, [root])


async def read_files(rt: TeamRuntime, root: str, rels: list[str]) -> dict[str, bytes]:
    data = await _py(rt, _READ, [root], rels)
    return {rel: base64.b64decode(b64) for rel, b64 in data.items()}


async def write_files(rt: TeamRuntime, root: str, files: list[dict[str, Any]]) -> dict[str, Any]:
    """files: [{"rel", "data" (bytes), "mtime", "mode"}]."""
    payload = [{**f, "data": base64.b64encode(f["data"]).decode()} for f in files]
    return await _py(rt, _WRITE, [root], payload)


def _author(swarm: Swarm, rt: TeamRuntime, uid: int) -> str | None:
    for a in rt.agents:
        if a.uid == uid:
            return a.name
    return None


async def run_encounter(swarm: Swarm) -> None:
    """Background task: wait for the encounter time, open the channel, then relay."""
    enc = swarm.scenario.encounter
    assert enc is not None
    # dry runs (mock agents finish in seconds) open the encounter early so it is exercised
    after = min(enc.after, DRY_RUN_ENCOUNTER_AFTER) if swarm.dry_model is not None else enc.after
    await anyio.sleep(max(0.0, after - (time.monotonic() - swarm.started)))
    if swarm.stopping:
        return
    via, path = enc.via, enc.path
    if via == "shared_dir":
        path = path or f"{WORKSPACE}/shared"
    elif via == "board_channel":
        path = path or "shared"
    # agents still in the run (working or asleep; sleepers are woken by the encounter itself)
    active = {rt.team.name: sum(1 for a in rt.agents if not swarm.agents[a.name].done) for rt in swarm.teams}
    transcript().info({"via": via, "path": path, "active_agents": active}, source="swarm.encounter")
    for team, count in active.items():
        if count == 0:
            add_problem(f"encounter opened with 0 active agents in team {team}")
    swarm.encounter_open = True
    swarm.wake.touch()  # the quiet-period clock restarts when the encounter opens

    if via == "board_channel":
        await _open_channel(swarm, path)
    if enc.announce:
        # an ordinary post by ops: in the new channel, or in #general
        await _announce(swarm, path if via == "board_channel" else "general", enc.announce)
    if via == "file":
        await _copy_file(swarm, path)
        return
    if via == "shared_dir":
        for rt in swarm.teams:
            await write_files(rt, path, [])  # make sure the folder exists
    while True:
        try:
            if via == "shared_dir":
                await sync_dirs(swarm, path)
            else:
                await mirror_channel(swarm, path)
        except Exception as ex:  # a failed pass must not end the run; try again next time
            transcript().info({"error": str(ex)[:500]}, source="swarm.encounter_error")
        await anyio.sleep(SYNC_SECONDS)


async def _copy_file(swarm: Swarm, dest: str | None) -> None:
    enc = swarm.scenario.encounter
    assert enc is not None and enc.source and dest
    text = render_dates(swarm.scenario.path(enc.source).read_text(), swarm.run_start)
    parent, _, name = dest.rstrip("/").rpartition("/")
    for rt in swarm.teams:
        result = await write_files(rt, parent or "/", [{"rel": name, "data": text.encode(), "mode": 0o664}])
        if result["failed"]:
            transcript().info(
                {"team": rt.team.name, "failed": result["failed"]}, source="swarm.encounter_error"
            )


# Creates /board/<channel> without following symlinks; an existing channel is kept as is.
_MKCHANNEL = r"""
import os, sys
board, name = sys.argv[1], sys.argv[2]
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
bfd = os.open(board, DIR)
try:
    os.mkdir(name, 0o3775, dir_fd=bfd)
    created = True
except FileExistsError:
    created = False
cfd = os.open(name, DIR, dir_fd=bfd)  # fails on a planted symlink
if created:
    os.fchmod(cfd, 0o3775)
print(os.fstat(cfd).st_uid)
"""


async def _open_channel(swarm: Swarm, channel: str) -> None:
    for rt in swarm.teams:
        assert rt.sandbox is not None
        result = await rt.sandbox.exec([PYTHON, "-I", "-c", _MKCHANNEL, BOARD, channel], user="root")
        if not result.success:
            add_problem(
                f"could not open board channel #{channel} for team {rt.team.name}: {result.stderr[-200:]}"
            )
        elif result.stdout.strip() != "0":
            transcript().info(
                {
                    "team": rt.team.name,
                    "note": f"#{channel} already existed, owned by uid {result.stdout.strip()}",
                },
                source="swarm.encounter_error",
            )


async def _announce(swarm: Swarm, channel: str, text: str) -> None:
    for rt in swarm.teams:
        assert rt.sandbox is not None
        await rt.sandbox.exec(
            ["/usr/local/bin/board", "post", channel, "-m", render_dates(text, swarm.run_start)],
            user=OPS_USER,
        )


async def sync_dirs(swarm: Swarm, root: str) -> None:
    """One two-way pass over the shared folder."""
    listings = {rt.team.name: await list_files(rt, root) for rt in swarm.teams}
    by_name = {rt.team.name: rt for rt in swarm.teams}
    # newest version of every path across teams
    best: dict[str, tuple[str, dict[str, Any]]] = {}
    for team, files in listings.items():
        for rel, meta in files.items():
            if rel not in best or meta["mtime"] > best[rel][1]["mtime"]:
                best[rel] = (team, meta)
    for target, files in listings.items():
        wanted: dict[str, list[str]] = {}
        for rel, (source, meta) in best.items():
            if source != target and files.get(rel, {}).get("sha") != meta["sha"]:
                wanted.setdefault(source, []).append(rel)
        for source, rels in wanted.items():
            contents = await read_files(by_name[source], root, rels)
            batch = [
                {"rel": rel, "data": data, "mtime": listings[source][rel]["mtime"], "mode": 0o664}
                for rel, data in contents.items()
            ]
            result = await write_files(by_name[target], root, batch)
            synced_paths = []
            author = None
            for rel in result["done"]:
                uid = listings[source][rel]["uid"]
                author = _author(swarm, by_name[source], uid)
                synced_paths.append(f"{root}/{rel}")
                transcript().info(
                    {
                        "from_team": source,
                        "to_team": target,
                        "path": f"{root}/{rel}",
                        "author_uid": uid,
                        "author_agent": author,
                    },
                    source="swarm.encounter_sync",
                )
            # files from another team arrive written by root, so the file poller can't attribute
            # them; tell the wake controller their real author so sleeping agents are woken
            swarm.wake.note_sync(by_name[target].sandbox_name, synced_paths, author)
            if result["failed"]:
                transcript().info(
                    {"to_team": target, "failed": result["failed"]}, source="swarm.encounter_error"
                )


async def mirror_channel(swarm: Swarm, channel: str) -> None:
    """Copy new posts in the shared channel to every other team's board.

    Only posts by a team's own agents travel, and only once the source team's scanner
    has recorded them as messages. The relayed copy's name takes its author from the
    post's owner uid, never from the original file name, so agents can't forge it.
    """
    root = f"{BOARD}/{channel}"
    listings = {rt.team.name: await list_files(rt, root) for rt in swarm.teams}
    for source_rt in swarm.teams:
        source = source_rt.team.name
        users = {a.uid: a.user for a in source_rt.agents}
        own_posts = {}
        for rel, meta in listings[source].items():
            message_id = source_rt.scanner.ids.get(f"{channel}/{rel}") if source_rt.scanner else None
            stamp = re.match(r"(\d{10,})-", rel)
            if "/" in rel or meta["uid"] not in users or message_id is None:
                continue
            ms = stamp.group(1) if stamp else str(int(meta["mtime"] * 1000))
            mirrored = f"{ms}-{users[meta['uid']]}@{source_rt.hostname}.md"
            own_posts[rel] = (mirrored, meta, message_id)
        for target_rt in swarm.teams:
            if target_rt is source_rt:
                continue
            pending = {rel: v for rel, v in own_posts.items() if v[0] not in listings[target_rt.team.name]}
            if not pending:
                continue
            contents = await read_files(source_rt, root, list(pending))
            batch = [
                {"rel": pending[rel][0], "data": data, "mtime": pending[rel][1]["mtime"], "mode": 0o644}
                for rel, data in contents.items()
            ]
            result = await write_files(target_rt, root, batch)
            by_mirrored = {v[0]: v for v in pending.values()}
            for name in result["done"]:
                _, _, message_id = by_mirrored[name]
                if target_rt.scanner is not None:
                    # the target's scanner treats the copy as the original message
                    key = f"{channel}/{name}"
                    target_rt.scanner.ids[key] = message_id
                    target_rt.scanner.known.add(key)
                original = swarm.log.get(message_id)
                if original is not None:
                    for agent in target_rt.agents:
                        if agent.name not in original.delivered_to:
                            original.delivered_to.append(agent.name)
            if result["failed"]:
                transcript().info(
                    {"to_team": target_rt.team.name, "failed": result["failed"]},
                    source="swarm.encounter_error",
                )
