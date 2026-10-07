"""Background processes with a dummy long-running command (no runs, no Docker)."""

import sys

from swarmbench.runner import procs
from tests.conftest import wait_for

SLEEPER = [sys.executable, "-c", "import time\nprint('hello', flush=True)\ntime.sleep(60)"]
STUBBORN = [
    sys.executable,
    "-c",
    "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\nprint('ready', flush=True)\ntime.sleep(60)",
]


def test_spawn_detached_runs_in_own_session_with_log(tmp_path):
    import os

    log = tmp_path / "out" / "run.log"
    pid, started = procs.spawn_detached(SLEEPER, log)
    try:
        assert procs.is_alive(pid, started)
        assert os.getsid(pid) == pid  # its own session: survives the terminal closing
        wait_for(lambda: "hello" in log.read_text())
    finally:
        procs.stop_process(pid, started, timeout=5, hard=True)


def test_reused_pid_is_not_ours(tmp_path):
    pid, started = procs.spawn_detached(SLEEPER, tmp_path / "log")
    try:
        # Same pid, different start time: treated as a different process and never signalled.
        assert not procs.is_alive(pid, started - 100)
        assert procs.stop_process(pid, started - 100, timeout=1) == "not-running"
        assert procs.is_alive(pid, started)
    finally:
        procs.stop_process(pid, started, timeout=5, hard=True)


def test_graceful_stop(tmp_path):
    pid, started = procs.spawn_detached(SLEEPER, tmp_path / "log")
    assert procs.stop_process(pid, started, timeout=10) == "stopped"
    assert not procs.is_alive(pid, started)
    assert procs.stop_process(pid, started) == "not-running"


def test_hard_stop_kills_a_process_that_ignores_sigint(tmp_path):
    log = tmp_path / "log"
    pid, started = procs.spawn_detached(STUBBORN, log)
    wait_for(lambda: "ready" in log.read_text())
    assert procs.stop_process(pid, started, timeout=0.5) == "still-running"
    assert procs.is_alive(pid, started)
    assert procs.stop_process(pid, started, timeout=0.5, hard=True) == "killed"
    assert not procs.is_alive(pid, started)


def test_missing_process():
    assert not procs.is_alive(None, None)
    assert not procs.is_alive(999_999_99, 1.0)
    assert procs.start_time(999_999_99) is None
