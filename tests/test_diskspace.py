"""Low-disk warnings before a launch. Fake Docker only."""

import subprocess
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from swarmbench import cli
from swarmbench.runner import control, diskspace, docker
from tests.conftest import cli_args

GB = diskspace.GB


@pytest.fixture
def checking(monkeypatch):
    monkeypatch.delenv(diskspace.CHECK_ENV, raising=False)
    monkeypatch.setattr(control, "images_to_prune", lambda **k: ([object()] * 3, ""))
    monkeypatch.setattr(docker, "reclaimable_images", lambda **k: "39.95GB (59%)")
    monkeypatch.setattr(diskspace, "uses_colima", lambda: True)


def test_no_warnings_with_room_to_spare(checking, monkeypatch, tmp_path):
    monkeypatch.setattr(diskspace, "host_free", lambda path: 200 * GB)
    monkeypatch.setattr(diskspace, "docker_free", lambda: 50 * GB)
    assert diskspace.warnings(tmp_path) == []


def test_low_host_disk_names_cleanup_and_trim(checking, monkeypatch, tmp_path):
    monkeypatch.setattr(diskspace, "host_free", lambda path: 6 * GB)
    monkeypatch.setattr(diskspace, "docker_free", lambda: 40 * GB)
    lines = diskspace.warnings(tmp_path)
    assert lines[0] == "Only 6.0 GB free on this computer's disk."
    assert "can remove 3 old swarmbench image(s); Docker counts 39.95GB (59%)" in lines[1]
    assert "fstrim" in lines[2]


def test_low_docker_disk_alone_skips_the_trim_hint(checking, monkeypatch, tmp_path):
    monkeypatch.setattr(diskspace, "host_free", lambda path: 200 * GB)
    monkeypatch.setattr(diskspace, "docker_free", lambda: 2 * GB)
    lines = diskspace.warnings(tmp_path)
    assert lines[0] == "Only 2.0 GB free on Docker's disk."
    assert not any("fstrim" in line for line in lines)


def test_unknown_sizes_and_the_off_switch(checking, monkeypatch, tmp_path):
    monkeypatch.setattr(diskspace, "host_free", lambda path: None)
    monkeypatch.setattr(diskspace, "docker_free", lambda: None)
    assert diskspace.warnings(tmp_path) == []
    monkeypatch.setattr(diskspace, "host_free", lambda path: 1 * GB)
    monkeypatch.setenv(diskspace.CHECK_ENV, "1")
    assert diskspace.warnings(tmp_path) == []


def test_no_docker_details_when_docker_did_not_answer(checking, monkeypatch, tmp_path):
    monkeypatch.setattr(diskspace, "host_free", lambda path: 6 * GB)
    monkeypatch.setattr(diskspace, "docker_free", lambda: None)
    monkeypatch.setattr(control, "images_to_prune", lambda **k: pytest.fail("Docker asked again"))
    assert diskspace.warnings(tmp_path) == [
        "Only 6.0 GB free on this computer's disk.",
        "`swarm cleanup` removes old swarmbench images.",
    ]


def test_every_docker_call_in_the_check_is_short(checking, monkeypatch, tmp_path):
    timeouts = []
    image = docker.Image("swarmbench-base:abc", "111111111111", datetime(2026, 10, 19, tzinfo=UTC))
    monkeypatch.setattr(docker, "swarm_images", lambda timeout=120: timeouts.append(timeout) or [image])

    def fake(*args, timeout=120):
        timeouts.append(timeout)
        return subprocess.CompletedProcess(args, 0, "h\noverlay 1 1 1024 99% /\n", "")

    monkeypatch.setattr(docker, "docker", fake)
    monkeypatch.setattr(diskspace, "host_free", lambda path: 200 * GB)
    diskspace.warnings(tmp_path)
    assert timeouts and all(t <= diskspace.DOCKER_TIMEOUT for t in timeouts)


def test_host_free_walks_up_to_an_existing_folder(tmp_path):
    assert diskspace.host_free(tmp_path / "not" / "yet") is not None


def test_docker_free_reads_df_in_a_container_from_a_local_image(monkeypatch):
    calls = []
    image = docker.Image("swarmbench-base:abc", "111111111111", datetime(2026, 10, 19, tzinfo=UTC))
    monkeypatch.setattr(docker, "swarm_images", lambda **k: [image])
    df = "Filesystem 1024-blocks Used Available Capacity Mounted on\noverlay 102624184 57603188 39761836 60% /\n"

    def fake(*args, timeout=120):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, df, "")

    monkeypatch.setattr(docker, "docker", fake)
    assert diskspace.docker_free() == 39761836 * 1024
    assert calls[0][:4] == ("run", "--rm", "--pull", "never") and "swarmbench-base:abc" in calls[0]
    monkeypatch.setattr(docker, "swarm_images", lambda **k: [])
    assert diskspace.docker_free() is None


def test_run_prints_disk_warnings_but_still_launches(monkeypatch, runs_base, scenario, fakes):
    monkeypatch.setattr(diskspace, "warnings", lambda folder: ["Only 6.0 GB free on this computer's disk."])
    result = CliRunner().invoke(cli.app, cli_args("run", str(scenario), "--dry-run", "--attached"))
    assert result.exit_code == 0, result.output
    assert "warning: Only 6.0 GB free on this computer's disk." in result.output
