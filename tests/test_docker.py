"""Hard-stop and cleanup against real Docker, with a small labelled container.

Skipped when Docker isn't running or the python:3.12-slim image isn't present locally
(the test never pulls an image). Only touches resources labelled with its own run id.
"""

import uuid

import pytest

from swarmbench.runner import control, docker, runs
from swarmbench.status import StatusWriter
from swarmbench.types import RunStatus

IMAGE = "python:3.12-slim"


def _docker_ready() -> bool:
    return docker.docker("image", "inspect", IMAGE, timeout=20).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ready(), reason=f"needs Docker and the {IMAGE} image")


@pytest.fixture
def labelled_run(runs_base):
    run_dir = runs.new_run_dir(f"dockertest-{uuid.uuid4().hex[:8]}")
    StatusWriter(run_dir, RunStatus(run_id=run_dir.run_id, scenario="dockertest", state="done"))
    label = f"{docker.RUN_LABEL}={run_dir.run_id}"
    volume = f"swarmbench-test-{uuid.uuid4().hex[:8]}"
    assert docker.docker("volume", "create", "--label", label, volume).returncode == 0
    started = docker.docker(
        "run", "-d", "--network", "none", "--label", label, "-v", f"{volume}:/data", IMAGE, "sleep", "300"
    )
    assert started.returncode == 0, started.stderr
    yield run_dir
    docker.remove_run(run_dir.run_id)  # in case the test failed part-way


def test_cleanup_finds_and_removes_a_runs_leftovers(labelled_run, runs_base):
    found = docker.labelled(labelled_run.run_id)
    assert sorted(r.kind for r in found) == ["container", "volume"]

    ended, _ = control.leftovers(runs_base)
    mine = [r for r in ended if r.run_id == labelled_run.run_id]
    assert sorted(r.kind for r in mine) == ["container", "volume"]

    assert docker.remove(mine) == []
    assert docker.labelled(labelled_run.run_id) == []


def test_remove_run_takes_everything_down(labelled_run):
    assert docker.remove_run(labelled_run.run_id) == []
    assert docker.labelled(labelled_run.run_id) == []
