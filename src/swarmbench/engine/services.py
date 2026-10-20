"""A scenario's background programs (``services:`` in scenario.yaml) inside a team container.

Each program runs as its own user from ``/srv/<name>/`` (readable only by that user), with a
private writable folder ``/var/lib/svc/<name>/`` and a socket ``/run/services/<name>.sock``
that agents connect to. The program can tell who is calling from the socket's peer
credentials (the kernel-checked uid). Agents can use it but can't read its files, change it
or stop it, since they are other non-root users.

At the end of the run the controller copies each private folder into
``runs/<id>/services/<team>/<name>/``: the program's output (``output.log``) and any records
it wrote there.
"""

from __future__ import annotations

import io
import shlex
import tarfile
from pathlib import Path
from typing import Any

from inspect_ai.util import SandboxEnvironment

from .layout import SERVICE_STATE_DIR, ServiceUser
from .snapshot import _read_root_file

PYTHON = "/usr/local/bin/python3"
START_SECONDS = 20
MAX_COLLECT_BYTES = 64 * 1024 * 1024


class ServiceError(RuntimeError):
    pass


def start_script(svc: ServiceUser, tz: str = "UTC") -> str:
    """Shell run as the program's user: start it in the background with a clean environment,
    then wait until its socket exists (or it exits)."""
    program = (
        f"{PYTHON} -I {shlex.quote(svc.command)}"
        if svc.command.endswith(".py")
        else (f"./{shlex.quote(svc.command)}")
    )
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": svc.state,
        "LANG": "C.UTF-8",
        "TZ": tz,
        "SERVICE_NAME": svc.name,
        "SERVICE_SOCKET": svc.socket,
        "SERVICE_STATE": svc.state,
    }
    assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    log = f"{svc.state}/output.log"
    tries = START_SECONDS * 10
    # umask 0: the socket must be connectable by agents; everything else the program writes
    # stays private because its folder is closed to them (0750, group: its own, plus root)
    return (
        f"set -e\ncd {svc.folder}\numask 000\n"
        f"nohup env -i {assignments} {program} >>{log} 2>&1 </dev/null &\n"
        f"pid=$!\n"
        f"for i in $(seq {tries}); do\n"
        f"  [ -S {svc.socket} ] && exit 0\n"
        f"  kill -0 $pid 2>/dev/null || break\n"
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


# Prints the uids of running processes, one per line (scans /proc as root).
_UIDS = r"""
import os
uids = set()
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    uids.add(line.split()[1])
                    break
    except OSError:
        pass
print("\n".join(sorted(uids)))
"""


async def running_uids(sandbox: SandboxEnvironment) -> set[int] | None:
    try:
        result = await sandbox.exec([PYTHON, "-I", "-c", _UIDS], user="root", timeout=60)
    except Exception:
        return None
    if not result.success:
        return None
    return {int(u) for u in result.stdout.split() if u.isdigit()}


async def collect_service(sandbox: SandboxEnvironment, svc: ServiceUser, dest: Path) -> list[str]:
    """Copy the program's private folder into ``dest``. Returns the files copied."""
    archive = f"/var/backups/svc-{svc.name}.tar.gz"
    result = await sandbox.exec(
        ["/bin/tar", "-C", SERVICE_STATE_DIR, "-czf", archive, svc.name], user="root", timeout=300
    )
    if not result.success:
        raise ServiceError(f"archiving failed: {result.stderr.strip()[-300:]}")
    try:
        blob = await _read_root_file(sandbox, archive)
    finally:
        await sandbox.exec(["/bin/rm", "-f", archive], user="root", timeout=60)
    if len(blob) > MAX_COLLECT_BYTES:
        raise ServiceError(f"archive too large ({len(blob)} bytes)")
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = []
        for m in tar.getmembers():
            parts = Path(m.name).parts
            if not parts or parts[0] != svc.name or not (m.isfile() or m.isdir()):
                continue  # only the program's own folder; links and devices are skipped
            m.name = str(Path(*parts[1:])) if len(parts) > 1 else "."
            members.append(m)
            if m.isfile():
                files.append(m.name)
        tar.extractall(dest, members=members, filter="data")
    return sorted(files)


async def finish_services(
    sandbox: SandboxEnvironment, services: list[ServiceUser], dest: Path | None
) -> tuple[dict[str, Any], list[str]]:
    """Whether each program was still running, and its files copied into ``dest/<name>/``.
    Returns (status per program, problems)."""
    status: dict[str, Any] = {}
    problems: list[str] = []
    uids = await running_uids(sandbox)
    for svc in services:
        entry: dict[str, Any] = {"running_at_end": None if uids is None else svc.uid in uids}
        if entry["running_at_end"] is False:
            problems.append(f"background program {svc.name} was not running at the end of the run")
        if dest is not None:
            try:
                entry["files"] = await collect_service(sandbox, svc, dest / svc.name)
            except Exception as ex:
                problems.append(
                    f"background program {svc.name}: its records were not collected ({str(ex)[:200]})"
                )
        status[svc.name] = entry
    return status, problems
