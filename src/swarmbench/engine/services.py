"""A scenario's background programs (``services:`` in scenario.yaml) inside a team container.

Each program runs as its own user from ``/srv/<name>/`` (readable only by that user), with a
private writable folder ``/var/lib/svc/<name>/`` and a socket
``/run/services/<name>/<name>.sock`` that agents connect to; only the program can write either
folder. The program can tell who is calling from the socket's peer credentials (the
kernel-checked uid). Agents can use it but can't read its files, change it or stop it, since
they are other non-root users. A small supervisor (``svcrun``) restarts it if it exits.

At the end of the run the program is stopped, then its private folder is copied, as its own
user (root in the container has no power to read other users' files), into
``runs/<id>/services/<team>/<name>/``: its output (``output.log``) and any records it wrote.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shlex
import tarfile
from pathlib import Path
from typing import Any

from inspect_ai.util import SandboxEnvironment

from .layout import SVCRUN_PATH, ServiceUser

PYTHON = "/usr/local/bin/python3"
START_SECONDS = 20
MAX_COLLECT_BYTES = 64 * 1024 * 1024
"""At most this many bytes of files (their full size, before compression) are copied out."""
MAX_COLLECT_FILES = 10_000
CHUNK = 6 * 1024 * 1024  # stays under Inspect's 10 MiB exec output limit after base64


class ServiceError(RuntimeError):
    pass


def start_script(svc: ServiceUser, tz: str = "UTC") -> str:
    """Shell run as the program's user: start it under the supervisor in the background with a
    clean environment, then wait until its socket is there and connectable."""
    # unbuffered, so its output is in the log when it is stopped
    program = [PYTHON, "-I", "-u", svc.command] if svc.command.endswith(".py") else [f"./{svc.command}"]
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": svc.state,
        "TMPDIR": svc.state,
        "LANG": "C.UTF-8",
        "TZ": tz,
        "SERVICE_NAME": svc.name,
        "SERVICE_SOCKET": svc.socket,
        "SERVICE_STATE": svc.state,
    }
    assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    command = shlex.join([PYTHON, "-I", SVCRUN_PATH, svc.socket, *program])
    log = f"{svc.state}/output.log"
    return (
        f"set -e\ncd {svc.folder}\numask 077\n"
        f"nohup env -i {assignments} {command} >>{log} 2>&1 </dev/null &\n"
        f"for i in $(seq {START_SECONDS * 10}); do\n"
        f'  [ -S {svc.socket} ] && [ "$(stat -c %a {svc.socket})" = 666 ] && exit 0\n'
        f"  sleep 0.1\n"
        f"done\n"
        f"echo 'background program {svc.name} did not open {svc.socket}' >&2\n"
        f"tail -c 2000 {log} >&2\nexit 1\n"
    )


async def start_services(sandbox: SandboxEnvironment, services: list[ServiceUser], tz: str = "UTC") -> None:
    for svc in services:
        result = await sandbox.exec(["/bin/sh", "-c", start_script(svc, tz)], user=svc.name, timeout=120)
        if not result.success:
            raise ServiceError(result.stderr.strip()[-2000:] or f"starting {svc.name} failed")


# Run as the program's user. Reports whether the program (not just its supervisor) was running,
# then stops every process of this user: SIGTERM, then SIGKILL after a few seconds. Only the
# program's own user can signal it (root in the container has no such power).
_STOP = r"""
import json, os, signal, sys, time
supervisor = sys.argv[1].encode()
def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            with open(f"/proc/{pid}/status") as f:
                pid = next(int(l.split()[1]) for l in f if l.startswith("PPid:"))
        except (OSError, StopIteration):
            break
    return out
me = ancestors()  # this script and whatever started it
def mine():
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) in me:
            continue
        try:
            st = os.stat(f"/proc/{pid}")
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        if st.st_uid == os.getuid():
            out[int(pid)] = args
    return out
procs = mine()
running = any(supervisor not in args for args in procs.values())
def signal_all(sig):
    for pid in mine():
        try:
            os.kill(pid, sig)
        except OSError:
            pass
# SIGTERM and a few seconds to finish; then SIGKILL, repeated until nothing is left (a
# process may fork between listing and signalling)
signal_all(signal.SIGTERM)
end = time.time() + 5
while mine() and time.time() < end:
    time.sleep(0.1)
end = time.time() + 5
while mine() and time.time() < end:
    signal_all(signal.SIGKILL)
    time.sleep(0.1)
print(json.dumps({"running": running, "left": len(mine())}))
"""

# Run as the program's user once it has stopped: a gzip'd tar of its private folder (regular
# files only, size and count capped), printing the bytes [offset, offset+limit) as base64 plus
# the total length. The archive is rebuilt identically on each call (nothing writes any more),
# so it is read in pieces without being stored anywhere.
_ARCHIVE = r"""
import base64, gzip, hashlib, io, json, os, stat, sys, tarfile
root, offset, limit, max_bytes, max_files = sys.argv[1], *map(int, sys.argv[2:6])
buf, total, count, skipped = io.BytesIO(), 0, 0, []
with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
    with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for here, dirs, files in os.walk(root):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(here, name)
                rel = os.path.relpath(path, root)
                try:
                    st = os.lstat(path)
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    total, count = total + st.st_size, count + 1
                    if total > max_bytes or count > max_files:
                        print(json.dumps({"error": f"over the limit of {max_bytes} bytes or {max_files} files"}))
                        sys.exit(0)
                    with open(path, "rb") as f:
                        info = tarfile.TarInfo(rel)
                        info.size, info.mtime, info.mode = st.st_size, int(st.st_mtime), 0o644
                        tar.addfile(info, f)
                except OSError:
                    skipped.append(rel)
data = buf.getvalue()
print(json.dumps({"size": len(data), "skipped": skipped, "sha": hashlib.sha256(data).hexdigest(),
                  "chunk": base64.b64encode(data[offset:offset + limit]).decode()}))
"""


async def stop_service(sandbox: SandboxEnvironment, svc: ServiceUser) -> tuple[bool | None, bool]:
    """Stop the program. Returns whether it was running beforehand (None if unknown) and
    whether it is now confirmed stopped."""
    try:
        result = await sandbox.exec([PYTHON, "-I", "-c", _STOP, SVCRUN_PATH], user=svc.name, timeout=60)
        reply = json.loads(result.stdout) if result.success else {}
    except Exception:
        reply = {}
    running = reply.get("running")
    return (None if running is None else bool(running)), reply.get("left") == 0


async def collect_service(sandbox: SandboxEnvironment, svc: ServiceUser, dest: Path) -> dict[str, Any]:
    """Copy the (stopped) program's private folder into ``dest``. Returns the files copied and
    any it couldn't read."""
    blob, skipped, sha = bytearray(), [], None
    while True:
        args = [svc.state, str(len(blob)), str(CHUNK), str(MAX_COLLECT_BYTES), str(MAX_COLLECT_FILES)]
        result = await sandbox.exec([PYTHON, "-I", "-c", _ARCHIVE, *args], user=svc.name, timeout=300)
        if not result.success:
            raise ServiceError(result.stderr.strip()[-300:] or f"exit {result.returncode}")
        reply = json.loads(result.stdout)
        if "error" in reply:
            raise ServiceError(reply["error"])
        if sha is not None and reply["sha"] != sha:
            raise ServiceError("its files changed while being copied")
        skipped, sha = reply["skipped"], reply["sha"]
        chunk = base64.b64decode(reply["chunk"])
        blob += chunk
        if len(blob) >= reply["size"] or not chunk:
            break
    if hashlib.sha256(blob).hexdigest() != sha:
        raise ServiceError("the copy is incomplete")
    files = []
    with tarfile.open(fileobj=io.BytesIO(bytes(blob)), mode="r:gz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        # checked again here: the archive came from inside the container
        if len(members) > MAX_COLLECT_FILES or sum(m.size for m in members) > MAX_COLLECT_BYTES:
            raise ServiceError("archive over the size or file limit")
        dest.mkdir(parents=True, exist_ok=True)
        tar.extractall(dest, members=members, filter="data")
        files = sorted(m.name for m in members)
    return {"files": files, "unreadable": skipped}


def restarts(log: Path) -> int:
    try:
        return sum(
            line.startswith("[svcrun] restart ") for line in log.read_text(errors="replace").splitlines()
        )
    except OSError:
        return 0


async def finish_services(
    sandbox: SandboxEnvironment, services: list[ServiceUser], dest: Path | None
) -> tuple[dict[str, Any], list[str]]:
    """Stop each program, note whether it was still running, and copy its files into
    ``dest/<name>/``. Returns (status per program, problems)."""
    status: dict[str, Any] = {}
    problems: list[str] = []
    for svc in services:
        running, stopped = await stop_service(sandbox, svc)
        entry: dict[str, Any] = {"running_at_end": running}
        if running is False:
            problems.append(f"background program {svc.name} was not running at the end of the run")
        if not stopped:
            # copying while it might still write could give a mixed or partial record
            problems.append(
                f"background program {svc.name} could not be stopped; its records were not collected"
            )
        elif dest is not None:
            try:
                entry |= await collect_service(sandbox, svc, dest / svc.name)
                entry["restarts"] = restarts(dest / svc.name / "output.log")
            except Exception as ex:
                problems.append(
                    f"background program {svc.name}: its records were not collected ({str(ex)[:200]})"
                )
            if entry.get("unreadable"):
                problems.append(
                    f"background program {svc.name}: unreadable files not collected: {entry['unreadable'][:5]}"
                )
            if entry.get("restarts"):
                problems.append(
                    f"background program {svc.name} stopped and was restarted {entry['restarts']} time(s)"
                )
        status[svc.name] = entry
    return status, problems
