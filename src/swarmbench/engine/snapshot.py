"""Workspace snapshots at the start and end of a run, and what changed between them.

Agents can edit the files a checker reads, so checker output alone can't be trusted.
Each team's /workspace is saved to ``runs/<id>/workspace/<team>/{start,end}.tar.gz``
(start: right after seeding; end: after the agents stop, while the container is up),
and a per-file summary of the changes goes into the sample store as
``swarm_workspace_diff``.

Snapshots are made as root without following symlinks; symlinks are recorded as
links and special files are skipped. Root has no permission override in these
containers, so a file its owner made private (mode 600) is read by its owner in a
second pass. Everything is bounded: files over ``MAX_FILE`` bytes, and anything past
``MAX_TOTAL`` bytes, are listed in the manifest but not archived (``truncated``).
A large ``.git/objects`` (over ``MAX_GIT_OBJECTS``) is skipped the same way.
"""

from __future__ import annotations

import base64
import io
import json
import tarfile
from pathlib import Path
from typing import Any

from inspect_ai.util import SandboxEnvironment

from swarmbench.types import AgentInfo

from .layout import WORKSPACE

PYTHON = "/usr/local/bin/python3"
SNAP_DIR = "/var/backups"
"""Root-only tmpfs where the archive is built before the host copies it out."""
MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 150 * 1024 * 1024
MAX_GIT_OBJECTS = 50 * 1024 * 1024
MAX_ENTRIES = 50_000
MAX_CHANGES = 2_000
"""At most this many changes are listed per team in the store (the archives have everything)."""

# Runs as root. Writes <out> (tar.gz) and prints the manifest as JSON.
# Every step goes through directory file descriptors opened with O_NOFOLLOW, and every
# file's metadata comes from the descriptor actually read, so an agent swapping a folder
# for a symlink mid-walk can't make root read anything outside /workspace.
_SNAPSHOT = r"""
import hashlib, io, json, os, stat, sys, tarfile
root, out, max_file, max_total, max_git, max_entries = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:7])
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
manifest, truncated, total = {}, [], 0

def open_root(path):
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    for part in [p for p in path.split("/") if p]:
        nxt = os.open(part, DIR, dir_fd=fd)
        os.close(fd)
        fd = nxt
    return fd

def du(dfd):
    size = 0
    for name in os.listdir(dfd):
        try:
            st = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISREG(st.st_mode):
            size += st.st_size
        elif stat.S_ISDIR(st.st_mode):
            try:
                sub = os.open(name, DIR, dir_fd=dfd)
            except OSError:
                continue
            try:
                size += du(sub)
            finally:
                os.close(sub)
    return size

rfd = open_root(root)
skip_git = False
try:
    gfd = open_root(os.path.join(root, ".git", "objects"))
    try:
        skip_git = du(gfd) > max_git
    finally:
        os.close(gfd)
except OSError:
    pass
tar = tarfile.open(out, "w:gz")

def entry_of(st, kind):
    return {"type": kind, "uid": st.st_uid, "mode": stat.S_IMODE(st.st_mode), "size": st.st_size,
            "mtime": st.st_mtime}

def tarinfo(rel, st, kind):
    info = tarfile.TarInfo(rel)
    info.mtime, info.mode = int(st.st_mtime), stat.S_IMODE(st.st_mode)
    info.uid, info.gid = st.st_uid, st.st_gid
    info.type = {"dir": tarfile.DIRTYPE, "link": tarfile.SYMTYPE, "file": tarfile.REGTYPE}[kind]
    return info

def add_file(dfd, name, rel, lst):
    global total
    entry = entry_of(lst, "file")
    if skip_git and rel.startswith(".git/objects/"):
        entry["skipped"] = "git objects too large"
        truncated.append(rel); manifest[rel] = entry; return
    if lst.st_size > max_file or total + lst.st_size > max_total:
        entry["skipped"] = "size cap"
        truncated.append(rel); manifest[rel] = entry; return
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except PermissionError:
        entry["unreadable"] = True; manifest[rel] = entry; return
    except OSError:
        return
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())  # the file actually opened
        if not stat.S_ISREG(st.st_mode):
            return
        entry = entry_of(st, "file")
        data = f.read(max_file + 1)
    if len(data) > max_file or total + len(data) > max_total:
        entry["skipped"] = "size cap"
        truncated.append(rel); manifest[rel] = entry; return
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    total += len(data)
    manifest[rel] = entry
    info = tarinfo(rel, st, "file")
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))

def walk(dfd, rel_dir):
    try:
        names = sorted(os.listdir(dfd))
    except OSError:
        if rel_dir:
            manifest[rel_dir]["unreadable"] = True
        return
    for name in names:
        if len(manifest) >= max_entries:
            truncated.append("(entry limit)"); return
        rel = f"{rel_dir}/{name}" if rel_dir else name
        try:
            lst = os.stat(name, dir_fd=dfd, follow_symlinks=False)
        except OSError:
            continue
        if stat.S_ISLNK(lst.st_mode):
            try:
                target = os.readlink(name, dir_fd=dfd)
            except OSError:
                continue
            entry = entry_of(lst, "link"); entry["target"] = target
            manifest[rel] = entry
            info = tarinfo(rel, lst, "link"); info.linkname = target
            tar.addfile(info)
        elif stat.S_ISDIR(lst.st_mode):
            try:
                sub = os.open(name, DIR, dir_fd=dfd)  # fails if it was swapped for a link
            except OSError:
                continue
            try:
                st = os.fstat(sub)
                manifest[rel] = entry_of(st, "dir")
                tar.addfile(tarinfo(rel, st, "dir"))
                walk(sub, rel)
            finally:
                os.close(sub)
        elif stat.S_ISREG(lst.st_mode):
            add_file(dfd, name, rel, lst)

walk(rfd, "")
os.close(rfd)
tar.close()
print(json.dumps({"manifest": manifest, "truncated": truncated, "total": total}))
"""

# Runs as one file owner: the listed files, as a base64 tar on stdout (bounded).
_OWNER_PASS = r"""
import base64, io, json, os, sys, tarfile, hashlib, stat
root, cap = sys.argv[1], int(sys.argv[2])
rels = json.loads(sys.stdin.read())
buf, out, total = io.BytesIO(), {}, 0
with tarfile.open(fileobj=buf, mode="w:gz") as tar:
    for rel in rels:
        try:
            fd = os.open(os.path.join(root, rel), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as f:
                st = os.fstat(f.fileno())
                data = f.read(cap + 1)
        except OSError:
            continue
        if total + len(data) > cap:
            continue
        total += len(data)
        out[rel] = hashlib.sha256(data).hexdigest()
        info = tarfile.TarInfo(rel)
        info.size, info.mtime, info.uid = len(data), int(st.st_mtime), st.st_uid
        info.mode = stat.S_IMODE(st.st_mode)
        tar.addfile(info, io.BytesIO(data))
print(json.dumps({"sha": out, "tar": base64.b64encode(buf.getvalue()).decode()}))
"""

OWNER_PASS_CAP = 6 * 1024 * 1024  # stays under Inspect's 10 MiB exec output limit after base64


async def snapshot(sandbox: SandboxEnvironment, agents: list[AgentInfo], dest: Path) -> dict[str, Any]:
    """Archive the team's /workspace to ``dest`` (a .tar.gz) and return its manifest."""
    archive = f"{SNAP_DIR}/{dest.name}"
    result = await sandbox.exec(
        [
            PYTHON,
            "-I",
            "-c",
            _SNAPSHOT,
            WORKSPACE,
            archive,
            str(MAX_FILE),
            str(MAX_TOTAL),
            str(MAX_GIT_OBJECTS),
            str(MAX_ENTRIES),
        ],
        user="root",
        timeout=600,
    )
    if not result.success:
        raise RuntimeError(f"workspace snapshot failed: {result.stderr.strip()[-500:]}")
    data = json.loads(result.stdout)
    manifest: dict[str, Any] = data["manifest"]
    blob = await _read_root_file(sandbox, archive)
    await sandbox.exec(["/bin/rm", "-f", archive], user="root")

    # second pass: private files, read by their owners
    by_uid: dict[int, list[str]] = {}
    for rel, e in manifest.items():
        if e.get("unreadable") and e["type"] == "file":
            by_uid.setdefault(e["uid"], []).append(rel)
    users = {a.uid: a.user for a in agents}
    extra: list[bytes] = []
    for uid, rels in by_uid.items():
        if uid not in users:
            continue
        r = await sandbox.exec(
            [PYTHON, "-I", "-c", _OWNER_PASS, WORKSPACE, str(OWNER_PASS_CAP)],
            input=json.dumps(rels),
            user=users[uid],
            timeout=300,
        )
        if not r.success:
            continue
        owner = json.loads(r.stdout)
        for rel, sha in owner["sha"].items():
            manifest[rel].pop("unreadable", None)
            manifest[rel]["sha256"] = sha
        extra.append(base64.b64decode(owner["tar"]))

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_merge_tars(blob, extra) if extra else blob)
    return {"manifest": manifest, "truncated": data["truncated"]}


_READ_CHUNK = r"""
import base64, os, sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW)
os.lseek(fd, int(sys.argv[2]), 0)
sys.stdout.write(base64.b64encode(os.read(fd, int(sys.argv[3]))).decode())
"""
CHUNK = 6 * 1024 * 1024


async def _read_root_file(sandbox: SandboxEnvironment, path: str) -> bytes:
    """Read a root-only file in chunks (``read_file`` can't see tmpfs mounts; exec output is capped)."""
    data = bytearray()
    while True:
        r = await sandbox.exec(
            [PYTHON, "-I", "-c", _READ_CHUNK, path, str(len(data)), str(CHUNK)], user="root"
        )
        if not r.success:
            raise RuntimeError(f"reading {path} failed: {r.stderr.strip()[-300:]}")
        chunk = base64.b64decode(r.stdout)
        data += chunk
        if len(chunk) < CHUNK:
            return bytes(data)


def _merge_tars(main: bytes, extras: list[bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as merged:
        for blob in [main, *extras]:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as part:
                for member in part.getmembers():
                    f = part.extractfile(member) if member.isfile() else None
                    merged.addfile(member, f)
    return out.getvalue()


def diff(start: dict[str, Any], end: dict[str, Any], agents: list[AgentInfo]) -> dict[str, Any]:
    """Per-path changes between two manifests: added, changed or deleted, with the final owner."""
    agent_of = {a.uid: a.name for a in agents}
    a, b = start["manifest"], end["manifest"]
    changes = []
    for path in sorted(set(a) | set(b)):
        old, new = a.get(path), b.get(path)
        if old is None:
            kind = "added"
        elif new is None:
            kind = "deleted"
        elif _fingerprint(old) != _fingerprint(new):
            kind = "changed"
        else:
            continue
        if (new or old)["type"] == "dir" and kind == "changed":
            continue  # a folder's own times change whenever its contents do
        final = new or {}
        changes.append(
            {
                "path": f"{WORKSPACE}/{path}",
                "change": kind,
                "type": (new or old)["type"],
                "uid": final.get("uid"),
                "agent": agent_of.get(final.get("uid")) if final else None,
                "sha_before": (old or {}).get("sha256"),
                "sha_after": (new or {}).get("sha256"),
                "size_before": (old or {}).get("size"),
                "size_after": (new or {}).get("size"),
                "unverified": bool(final.get("unreadable") or final.get("skipped")),
            }
        )
    truncated = bool(start["truncated"] or end["truncated"]) or len(changes) > MAX_CHANGES
    return {
        "changes": changes[:MAX_CHANGES],
        "total_changes": len(changes),
        "truncated": truncated,
        "notes": sorted(set(start["truncated"]) | set(end["truncated"]))[:50],
    }


def _fingerprint(entry: dict[str, Any]) -> tuple[Any, ...]:
    if entry["type"] == "link":
        return ("link", entry.get("target"))
    if entry["type"] == "dir":
        return ("dir", entry["mode"], entry["uid"])
    # without a digest (skipped or unreadable), fall back to size and time
    return ("file", entry.get("sha256") or (entry["size"], entry["mtime"]), entry["mode"], entry["uid"])
