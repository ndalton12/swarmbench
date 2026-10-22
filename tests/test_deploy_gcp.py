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


def fake_gcloud(tmp_path, labelled=True):
    """A gcloud that only records its calls: logged in, the VM exists, ssh always fails."""
    fake, log = tmp_path / "gcloud", tmp_path / "calls"
    label = "1" if labelled else ""
    fake.write_text(
        "#!/bin/bash\n"
        'echo "gcloud $*" >> "$FAKE_LOG"\n'
        'case "$*" in *"auth list"*) echo me@example.org ;;'
        f' *labels.swarmbench*) echo "{label}" ;; *maxRunDuration*) echo "" ;; *"instances describe"*) echo RUNNING ;;'
        ' *"instances list"*) echo us-central1-b ;;'
        ' *"compute ssh"*) exit 1 ;; esac\n'
    )
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_LOG": str(log)}
    return env, log


def test_sync_reaches_the_vm_through_iap(tmp_path):
    env, log = fake_gcloud(tmp_path)
    run("sync", "--zone", "us-central1-b", env=env)
    ssh = [line for line in log.read_text().splitlines() if "compute ssh" in line]
    assert ssh, log.read_text()
    assert (
        "compute ssh niall-dev --zone us-central1-b --tunnel-through-iap --quiet --ssh-flag=-T -- rsync --server" in ssh[0]
    )


def test_vms_the_script_did_not_create_are_left_alone(tmp_path):
    env, log = fake_gcloud(tmp_path, labelled=False)
    for cmd in ("delete", "stop", "sync"):
        out = run(cmd, "--name", "someone-elses-vm", "--yes", env=env)
        assert out.returncode != 0 and "refusing to touch it" in out.stderr, cmd
    assert "instances delete" not in log.read_text() and "instances stop" not in log.read_text()


def test_env_is_never_copied_with_rsync():
    text = SCRIPT.read_text()
    assert "umask 077 && cat > swarmbench/.env" in text
    assert not any("rsync" in line and ".env" in line and "Refusing" not in line
                   for line in text.splitlines() if not line.lstrip().startswith("#"))  # fmt: skip


def test_commands_find_the_vms_zone(tmp_path):
    env, log = fake_gcloud(tmp_path)
    run("sync", env=env)  # no --zone
    calls = log.read_text()
    assert "instances list --filter=name=niall-dev" in calls
    assert "describe niall-dev --zone us-central1-b" in calls
    assert "compute ssh niall-dev --zone us-central1-b" in calls


def test_launch_keeps_the_default_zone():
    assert "--zone us-central1-a" in run("launch", "--print").stdout


def test_keep_alive_sets_both_stops_off_on_the_vm(tmp_path):
    env, log = fake_gcloud(tmp_path)
    run("keep-alive", "on", env=env)
    ssh = [line for line in log.read_text().splitlines() if "compute ssh" in line]
    assert (
        ssh
        and "IDLE_MINUTES=0" in ssh[-1]
        and "MAX_UPTIME_HOURS=0" in ssh[-1]
        and "sudo tee /etc/vm-idle-stop" in ssh[-1]
    )


def test_keep_alive_off_restores_the_defaults():
    out = run("keep-alive", "off", "--print").stdout
    assert "IDLE_MINUTES=120 MAX_UPTIME_HOURS=24" in out


def test_launch_with_keep_alive_warns_about_billing():
    out = run("launch", "--print", "--keep-alive")
    assert "keep-alive: the VM never stops by itself" in out.stderr
    assert "--max-run-duration" not in out.stdout
