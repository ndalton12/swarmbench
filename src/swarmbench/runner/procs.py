"""Background processes: start them detached, check they are still ours, stop them.

A process is identified by its pid *and* its start time. Pids get reused, so before
signalling a pid we check that the process now holding it started at the recorded time.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil

# Start times are compared with this tolerance (seconds); psutil reports them as floats.
START_TOLERANCE = 1.0

# Children started by this process, kept so their exit statuses can be collected.
_children: list[subprocess.Popen] = []


def start_time(pid: int) -> float | None:
    """When the process with this pid started (seconds since the epoch), or None if gone."""
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def is_alive(pid: int | None, started: float | None) -> bool:
    """True if ``pid`` is still the same, still-running process that started at ``started``."""
    if not pid or started is None:
        return False
    try:
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_ZOMBIE:
            return False
        return abs(proc.create_time() - started) < START_TOLERANCE
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def spawn_detached(args: list[str], log_file: Path, cwd: Path | None = None) -> tuple[int, float]:
    """Start ``args`` in its own session, with output appended to ``log_file``.

    The child keeps running after this process (and its terminal) exits. Returns the
    child's pid and start time.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "ab") as log:
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=cwd,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    started = start_time(proc.pid)
    _children.append(proc)
    return proc.pid, started if started is not None else time.time()


def reap() -> None:
    """Collect exit statuses of finished children, so they don't linger as zombies."""
    for proc in list(_children):
        if proc.poll() is not None:
            _children.remove(proc)


def python_command(*args: str) -> list[str]:
    """Command line that runs the swarm CLI with this interpreter."""
    return [sys.executable, "-m", "swarmbench.cli", *args]


def send(pid: int, started: float | None, sig: signal.Signals) -> bool:
    """Send a signal, but only if the pid still belongs to the recorded process."""
    if not is_alive(pid, started):
        return False
    try:
        os.kill(pid, sig)
        return True
    except ProcessLookupError:
        return False


def wait_gone(pid: int, started: float | None, timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for the process to exit. True if it is gone."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reap()
        if not is_alive(pid, started):
            return True
        time.sleep(0.2)
    reap()
    return not is_alive(pid, started)


def stop_process(pid: int, started: float | None, timeout: float = 60.0, hard: bool = False) -> str:
    """Stop a recorded process.

    Graceful: send SIGINT (like Ctrl-C) and wait. With ``hard``, if it is still running
    after the wait, send SIGTERM, then SIGKILL. Returns what happened, in a word:
    ``not-running``, ``stopped``, ``killed`` or ``still-running``.
    """
    if not send(pid, started, signal.SIGINT):
        return "not-running"
    if wait_gone(pid, started, timeout):
        return "stopped"
    if not hard:
        return "still-running"
    send(pid, started, signal.SIGTERM)
    if wait_gone(pid, started, 10):
        return "killed"
    send(pid, started, signal.SIGKILL)
    wait_gone(pid, started, 5)
    return "killed"
