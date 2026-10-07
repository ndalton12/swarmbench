"""Live status file for a run (runs/<id>/status.json)."""

from __future__ import annotations

import os
import time
from typing import Any

from swarmbench.paths import RunDir
from swarmbench.types import RunStatus, now


class StatusWriter:
    """Holds a RunStatus and writes it to disk at most every ``interval`` seconds.

    Writes are atomic (temp file then rename) so readers never see half a file.
    """

    def __init__(self, run_dir: RunDir, status: RunStatus, interval: float = 3.0) -> None:
        self.run_dir = run_dir
        self.status = status
        self.interval = interval
        self._last = 0.0
        self.flush()

    def update(self, force: bool = False, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.status, key, value)
        if force or time.monotonic() - self._last >= self.interval:
            self.flush()

    def flush(self) -> None:
        self.status.updated = now()
        tmp = self.run_dir.status.with_suffix(".json.tmp")
        tmp.write_text(self.status.model_dump_json(indent=2))
        os.replace(tmp, self.run_dir.status)
        self._last = time.monotonic()


def read_status(run_dir: RunDir) -> RunStatus | None:
    try:
        return RunStatus.model_validate_json(run_dir.status.read_text())
    except (FileNotFoundError, ValueError):
        return None
