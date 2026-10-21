"""deploy/gcp.sh without Google Cloud: --print, and a stand-in gcloud that only records calls."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "gcp.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("rsync") is None, reason="needs bash and rsync"
)


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)


def test_launch_print_shows_the_vm_and_runs_nothing():
    out = run("launch", "--print").stdout
    create = next(line for line in out.splitlines() if line.startswith("+ gcloud"))
    for flag in (
        "--project kirk-souly-c11-vm", "instances create niall-dev", "--zone us-central1-a",
        "--machine-type n4a-standard-48", "--image-family ubuntu-2404-lts-arm64",
        "--boot-disk-type hyperdisk-balanced", "--boot-disk-size 250GB",
        "--service-account vm-runtime-sa@kirk-souly-c11-vm.iam.gserviceaccount.com",
        "--scopes cloud-platform", "--tags iap-ssh", "--no-address",
        "--max-run-duration 24h", "--instance-termination-action STOP",
    ):  # fmt: skip
        assert flag in create, flag
    assert "nothing was run" in out


def test_options_change_the_vm():
    out = run(
        "launch", "--print", "--type", "n4a-standard-16", "--public-ip", "--max-uptime-hours", "0"
    ).stdout
    assert "--machine-type n4a-standard-16" in out
    assert "--no-address" not in out and "--max-run-duration" not in out


def test_bad_names_and_options_are_refused():
    assert "not a valid VM name" in run("launch", "--name", "Bad_Name").stderr
    assert run("launch", "--bogus").returncode == 2


def test_sync_reaches_the_vm_through_iap(tmp_path):
    fake = tmp_path / "gcloud"
    log = tmp_path / "calls"
    fake.write_text(
        "#!/bin/bash\n"
        'echo "gcloud $*" >> "$FAKE_LOG"\n'
        'case "$*" in *"auth list"*) echo me@example.org ;; *"instances describe"*) echo RUNNING ;;'
        ' *"compute ssh"*) exit 1 ;; esac\n'
    )
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    run("sync", "--zone", "us-central1-b", env=env)
    ssh = [line for line in log.read_text().splitlines() if "compute ssh" in line]
    assert ssh, log.read_text()
    assert (
        "compute ssh niall-dev --zone us-central1-b --tunnel-through-iap --quiet -- rsync --server" in ssh[0]
    )
