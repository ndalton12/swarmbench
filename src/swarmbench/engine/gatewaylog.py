"""Collecting the gateway's request records from each container, a bounded chunk at a time.

The gateway appends JSON lines to a root-only file inside the container. Fetching it in
one go at the end could exceed Inspect's exec output limit (10 MiB) after a flood, and a
failed fetch would silently lose the evidence. Instead the controller drains it during
the run: each pass reads at most CHUNK bytes from where the last one stopped, keeps only
complete lines, and stores them on the host (in memory and in runs/<id>/gateway/). Any
failure to collect is recorded as an evidence gap in ``swarm_problems``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspect_ai.util import SandboxEnvironment

from .layout import RELAY_LOG, RELAY_PATH

PYTHON = "/usr/local/bin/python3"
CHUNK = 4 * 1024 * 1024  # bytes per read, well under the exec output limit
MAX_STORE_RECORDS = 50_000
"""At most this many records go into the sample store; the full set stays in the run folder."""

# Prints up to N bytes of the log from OFFSET, cut back to the last complete line.
_READ = r"""
import os, sys
path, offset, limit = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
try:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
except FileNotFoundError:
    sys.exit(0)
with os.fdopen(fd, "rb") as f:
    f.seek(offset)
    data = f.read(limit)
end = data.rfind(b"\n")
sys.stdout.buffer.write(data[: end + 1] if end >= 0 else b"")
"""


# Is the gateway still running? Prints "alive" or "dead" (scans /proc as root).
_ALIVE = r"""
import os, sys
target = sys.argv[1].encode()
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().split(b"\0")
    except OSError:
        continue
    # the gateway runs the script by path; this check (and any wrapper around it) has "-c"
    if target in args and b"-c" not in args:
        print("alive"); sys.exit(0)
print("dead")
"""


@dataclass
class GatewayCollector:
    sandbox_name: str
    sandbox: SandboxEnvironment
    out_file: Path | None = None
    offset: int = 0
    records: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    died_at: float | None = None
    """When the gateway was first found not running (wall-clock time), if it died."""

    async def check_alive(self) -> bool:
        """Record (once) if the gateway process has died. Returns whether it's running."""
        if self.died_at is not None:
            return False
        try:
            result = await self.sandbox.exec(
                [PYTHON, "-I", "-c", _ALIVE, RELAY_PATH], user="root", timeout=60
            )
        except Exception:  # noqa: BLE001 - can't tell; don't call it dead
            return True
        if result.success and result.stdout.strip() == "dead":
            import time

            self.died_at = time.time()
            return False
        return True

    async def drain(self, max_chunks: int = 8) -> int:
        """Read new records (up to ``max_chunks`` chunks). Returns how many were added."""
        added = 0
        for _ in range(max_chunks):
            try:
                result = await self.sandbox.exec(
                    [PYTHON, "-I", "-c", _READ, RELAY_LOG, str(self.offset), str(CHUNK)],
                    user="root",
                    timeout=120,
                )
            except Exception as ex:  # noqa: BLE001 - recorded as an evidence gap
                self.errors.append(f"{type(ex).__name__}: {str(ex)[:200]}")
                return added
            if not result.success:
                self.errors.append(result.stderr.strip()[-200:] or f"exit {result.returncode}")
                return added
            text = result.stdout
            if not text:
                return added
            self.offset += len(text.encode("utf-8"))
            lines = text.splitlines()
            batch = []
            for line in lines:
                try:
                    rec = json.loads(line)
                except ValueError:
                    self.errors.append("unreadable gateway record")
                    continue
                rec["sandbox"] = self.sandbox_name
                batch.append(rec)
            self.records.extend(batch)
            added += len(batch)
            if self.out_file is not None:
                self.out_file.parent.mkdir(parents=True, exist_ok=True)
                with self.out_file.open("a") as f:
                    f.writelines(json.dumps(r) + "\n" for r in batch)
            if len(text.encode("utf-8")) < CHUNK // 2:
                return added  # caught up
        return added
