"""Stopping runs and experiments, and cleaning up leftover Docker resources."""

from __future__ import annotations

import json
import os
import signal
import time
from collections.abc import Callable
from pathlib import Path

from swarmbench.paths import RunDir
from swarmbench.runner import docker, procs, runs
from swarmbench.runner.experiment import experiment_dir, read_supervisor, write_supervisor
from swarmbench.runner.listing import all_rows
from swarmbench.status import StatusWriter, read_status
from swarmbench.types import RunStatus, now

Say = Callable[[str], None]

# Seconds a hard stop waits after SIGTERM before SIGKILL.
TERM_GRACE = 10.0
# Seconds to let the engine wind a run down by itself before interrupting it.
DEFAULT_GRACE = 45.0
# Seconds to wait for a just-launched run to record its pid.
STARTUP_WAIT = 15.0


def _mark_stopped(run_dir: RunDir, reason: str) -> None:
    """Record a stop for a run whose process ended without saying so itself."""
    status = read_status(run_dir)
    if status is None or status.state not in runs.ACTIVE_STATES:
        return
    StatusWriter(run_dir, status.model_copy(update={"state": "stopped", "finished": now(), "error": reason}))


def _wait_for_pid(run_dir: RunDir, seconds: float) -> RunStatus | None:
    """A just-launched worker records its pid within a second or two; wait for it."""
    deadline = time.monotonic() + seconds
    status = read_status(run_dir)
    while (status is None or not status.pid) and time.monotonic() < deadline:
        time.sleep(0.2)
        status = read_status(run_dir)
    return status


def stop_runs(
    run_dirs: list[RunDir],
    hard: bool = False,
    timeout: float = 60.0,
    grace: float = DEFAULT_GRACE,
    say: Say = print,
) -> dict[str, str]:
    """Stop runs together, in steps, and return run id -> outcome.

    1. Write each run's stop_requested file. The engine checks it every second and winds
       the agents down cleanly, so the Inspect log is complete. Wait up to ``grace`` seconds.
    2. Send SIGINT to runs still going (Inspect cancels the sample) and wait up to ``timeout``.
    3. With ``hard``: SIGTERM, then SIGKILL, then remove the runs' containers.
    """
    outcome: dict[str, str] = {}
    waiting: list[tuple[RunDir, int, float | None]] = []
    for rd in run_dirs:
        status = read_status(rd)
        if status is None or status.state not in runs.ACTIVE_STATES:
            outcome[rd.run_id] = "not running"
            continue
        # Ask first, so even a run whose worker hasn't started yet sees the request.
        runs.request_stop(rd, "stopped by swarm stop")
        if not status.pid:
            status = _wait_for_pid(rd, min(grace, STARTUP_WAIT))
        if status is None or not status.pid:
            outcome[rd.run_id] = "stop requested"  # its worker will see the request when it starts
            continue
        if not procs.is_alive(status.pid, status.pid_started):
            outcome[rd.run_id] = "not running"
            continue
        waiting.append((rd, status.pid, status.pid_started))
        say(f"stopping {rd.run_id} (pid {status.pid})")

    def wait_all(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        for rd, pid, started in waiting:
            if rd.run_id not in outcome and procs.wait_gone(
                pid, started, max(0.0, deadline - time.monotonic())
            ):
                outcome[rd.run_id] = "stopped"

    wait_all(grace)
    for rd, pid, started in waiting:
        if rd.run_id not in outcome:
            say(f"{rd.run_id} hasn't stopped after {grace:.0f}s; interrupting it")
            procs.send(pid, started, signal.SIGINT)
    wait_all(timeout)

    for rd, pid, started in waiting:
        if rd.run_id in outcome:
            continue
        if hard:
            procs.send(pid, started, signal.SIGTERM)
            if not procs.wait_gone(pid, started, TERM_GRACE):
                procs.send(pid, started, signal.SIGKILL)
                procs.wait_gone(pid, started, 5)
            outcome[rd.run_id] = "killed"
        else:
            outcome[rd.run_id] = "still stopping"
            say(f"{rd.run_id} is still shutting down; use --hard to kill it and its containers")

    for rd in run_dirs:
        if outcome[rd.run_id] in ("stopped", "killed"):
            _mark_stopped(rd, "stopped by swarm stop")
        if hard:
            status = read_status(rd)
            failures = docker.remove_run(rd.root, rd.run_id, status.compose_project if status else None)
            for f in failures:
                say(f"could not remove {f}")
            if outcome[rd.run_id] == "not running":
                _mark_stopped(rd, "stopped by swarm stop --hard")
    return outcome


def stop_experiment(
    name: str,
    hard: bool = False,
    timeout: float = 60.0,
    base: Path | None = None,
    say: Say = print,
    grace: float = DEFAULT_GRACE,
) -> dict[str, str]:
    """Stop an experiment's supervisor (so no new runs start), then all of its runs."""
    state = read_supervisor(name, base)
    # A foreground experiment's supervisor is this process: it has stopped already.
    if state and state.pid != os.getpid() and procs.send(state.pid or 0, state.pid_started, signal.SIGINT):
        say(f"stopping experiment {name} (supervisor pid {state.pid})")
        if not procs.wait_gone(state.pid or 0, state.pid_started, 15):
            procs.send(state.pid or 0, state.pid_started, signal.SIGKILL)
            procs.wait_gone(state.pid or 0, state.pid_started, 5)
    state = read_supervisor(name, base)
    if state and state.state in ("starting", "running"):
        state.state = "stopped"
        write_supervisor(state, base)
    rows = [r for r in all_rows(base, experiment=name) if r.status.state in runs.ACTIVE_STATES or hard]
    return stop_runs([r.run_dir for r in rows], hard=hard, timeout=timeout, grace=grace, say=say)


def stop(
    ref: str,
    hard: bool = False,
    timeout: float = 60.0,
    base: Path | None = None,
    say: Say = print,
    grace: float = DEFAULT_GRACE,
) -> dict[str, str]:
    """Stop a run (by id or folder) or a whole experiment (by name)."""
    if experiment_dir(ref, base).is_dir() and not (
        Path(ref).is_dir() and (Path(ref) / "status.json").exists()
    ):
        return stop_experiment(ref, hard=hard, timeout=timeout, base=base, say=say, grace=grace)
    return stop_runs([runs.find_run(ref, base)], hard=hard, timeout=timeout, grace=grace, say=say)


def run_state(resource: docker.Resource, base: Path | None = None) -> str:
    """``alive``, ``ended``, or ``unknown`` when the resource's run isn't in this runs folder
    (it may belong to another checkout or working folder, so it is left alone by default)."""
    if not resource.run_id:
        return "unknown"
    run_dir = RunDir((base or runs.runs_base()) / resource.run_id)
    if not resource.belongs_to(run_dir.root):
        return "unknown"
    status = read_status(run_dir)
    if status is None:
        return "unknown"
    alive = status.state in runs.ACTIVE_STATES and procs.is_alive(status.pid, status.pid_started)
    return "alive" if alive else "ended"


def leftovers(base: Path | None = None) -> tuple[list[docker.Resource], list[docker.Resource]]:
    """Docker resources labelled by swarmbench whose run is not running.

    Returns two lists: resources of runs in this runs folder that have ended, and resources
    of runs this folder doesn't know about.
    """
    ended, unknown = [], []
    for r in docker.labelled():
        state = run_state(r, base)
        if state == "ended":
            ended.append(r)
        elif state == "unknown":
            unknown.append(r)
    return ended, unknown


def mark_dead_runs(base: Path | None = None) -> list[str]:
    """Runs that say they are active but whose process is gone: take down their containers
    (``docker compose down`` for the run's project and anything labelled with the run) and
    mark them failed. Returns their run ids."""
    marked = []
    for row in all_rows(base):
        if row.state == "died":
            docker.remove_run(row.run_dir.root, row.run_id, row.status.compose_project)
            StatusWriter(
                row.run_dir,
                row.status.model_copy(
                    update={"state": "failed", "finished": now(), "error": "the run's process died"}
                ),
            )
            marked.append(row.run_id)
    return marked


DEFAULT_KEEP_IMAGES = 5


def _run_images(run_dir: RunDir) -> list[str] | None:
    """Image tags a run uses, from its provenance.json (None if not written yet)."""
    try:
        data = json.loads(run_dir.provenance.read_text())
    except (FileNotFoundError, ValueError):
        return None
    return [i["tag"] for i in data.get("images", []) if isinstance(i, dict) and "tag" in i]


def images_to_prune(
    keep: int = DEFAULT_KEEP_IMAGES, base: Path | None = None
) -> tuple[list[docker.Image], str]:
    """swarmbench-team images that can go, and a one-line explanation.

    Kept: the newest ``keep``, any image a live run in this runs folder uses, and any image a
    container on this machine uses (which covers live runs from other checkouts). While a live
    run here hasn't recorded its images yet (it may be building them), nothing is pruned.
    """
    images = docker.team_images()
    if not images:
        return [], "No swarmbench-team images."
    protected: set[str] = set()
    for row in all_rows(base):
        if row.state not in runs.ACTIVE_STATES:
            continue
        tags = _run_images(row.run_dir)
        if tags is None:
            return [], f"{row.run_id} is starting and may be building images, so images were left alone."
        protected.update(tags)
    used = docker.images_used_by_containers()
    used_ids = {u.removeprefix("sha256:")[:12] for u in used}

    def in_use(image: docker.Image) -> bool:
        return image.tag in protected or image.tag in used or image.id[:12] in used_ids

    prune = [img for img in images[keep:] if not in_use(img)]
    kept = len(images) - len(prune)
    return prune, (
        f"{len(images)} swarmbench-team images; keeping {kept} (the newest {keep} and any in use)."
    )
