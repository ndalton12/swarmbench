"""Docker test: run the watcher in a plain two-user container and check it
attributes a cross-user TCP connection to the connecting user's uid.

This is the real proof of the bridge-attribution mechanism: an agent (uid 2001)
connects to another agent's bridge port, and the watcher, reading
``/proc/net/tcp`` as root, records the *client's* uid against that port.

Skipped automatically when Docker or the base image is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

IMAGE = "python:3.12-slim"
WATCHER = Path(__file__).resolve().parents[1] / "src" / "swarmbench" / "monitor" / "watcher.py"
PROBE = Path(__file__).resolve().parent / "docker" / "watcher_probe.py"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=30, check=True)
    except Exception:
        return False
    # image must be present locally (the sandbox is offline; do not pull)
    out = subprocess.run(
        ["docker", "image", "inspect", IMAGE], capture_output=True, timeout=30
    )
    return out.returncode == 0


pytestmark = pytest.mark.skipif(not _docker_available(), reason="docker or base image unavailable")


def test_watcher_attributes_cross_user_connection():
    cmd = [
        "docker", "run", "--rm",
        "--network", "none",  # the bridge connection is localhost-only
        "-v", f"{WATCHER}:/watcher.py:ro",
        "-v", f"{PROBE}:/probe.py:ro",
        IMAGE,
        "python3", "-I", "/probe.py",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    records = json.loads(result.stdout.strip().splitlines()[-1])
    # The watcher should have recorded the client (uid 2001) reaching port 3002.
    assert any(
        r.get("port") == 3002 and r.get("peer_uid") == 2001 for r in records
    ), f"expected uid 2001 -> port 3002 in {records}"
    # It must NOT mis-attribute the connection to the server's uid (2002).
    assert not any(
        r.get("port") == 3002 and r.get("peer_uid") == 2002 for r in records
    ), f"server uid 2002 wrongly recorded as the client in {records}"
