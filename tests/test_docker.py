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


def _start(run_id, run_folder, volume=None):
    labels = ["--label", f"{docker.RUN_LABEL}={run_id}", "--label", f"{docker.RUN_DIR_LABEL}={run_folder}"]
    mount = ["-v", f"{volume}:/data"] if volume else []
    started = docker.docker("run", "-d", "--network", "none", *labels, *mount, IMAGE, "sleep", "300")
    assert started.returncode == 0, started.stderr
    return started.stdout.strip()


@pytest.fixture
def labelled_run(runs_base):
    run_dir = runs.new_run_dir(f"dockertest-{uuid.uuid4().hex[:8]}")
    StatusWriter(run_dir, RunStatus(run_id=run_dir.run_id, scenario="dockertest", state="done"))
    volume = f"swarmbench-test-{uuid.uuid4().hex[:8]}"
    made = docker.docker("volume", "create", "--label", f"{docker.RUN_LABEL}={run_dir.run_id}", volume)
    assert made.returncode == 0
    _start(run_dir.run_id, run_dir.root.resolve(), volume)
    yield run_dir
    # In case the test failed part-way, remove everything with this run id.
    docker.remove(docker.labelled(run_dir.run_id))


def test_cleanup_finds_and_removes_a_runs_leftovers(labelled_run, runs_base):
    found = docker.labelled(labelled_run.run_id)
    assert sorted(r.kind for r in found) == ["container", "volume"]

    ended, _ = control.leftovers(runs_base)
    mine = [r for r in ended if r.run_id == labelled_run.run_id]
    assert sorted(r.kind for r in mine) == ["container", "volume"]

    assert docker.remove(mine) == []
    assert docker.labelled(labelled_run.run_id) == []


def test_remove_run_takes_everything_down(labelled_run):
    assert docker.remove_run(labelled_run.root, labelled_run.run_id) == []
    assert docker.labelled(labelled_run.run_id) == []


def test_same_run_id_from_another_checkout_is_left_alone(labelled_run, runs_base, tmp_path):
    """Run ids are only unique per runs folder; the run-folder label keeps others' containers safe."""
    other = _start(labelled_run.run_id, tmp_path / "other-checkout" / "runs" / labelled_run.run_id)
    ended, unknown = control.leftovers(runs_base)
    # docker ps shows short ids; docker run printed the full one.
    assert not any(other.startswith(r.id) for r in ended)
    assert any(other.startswith(r.id) for r in unknown)
    assert docker.remove_run(labelled_run.root, labelled_run.run_id) == []
    remaining = docker.labelled(labelled_run.run_id)
    assert len(remaining) == 1 and other.startswith(remaining[0].id)
