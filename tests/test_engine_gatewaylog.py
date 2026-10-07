"""Draining the gateway log in bounded chunks, and recording collection failures."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass

from swarmbench.engine import gatewaylog
from swarmbench.engine.gatewaylog import GatewayCollector


@dataclass
class Result:
    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class FakeSandbox:
    """Runs the collector's read script locally against a file standing in for the log."""

    def __init__(self, path: str, fail: bool = False) -> None:
        self.path, self.fail = path, fail
        self.calls = 0

    async def exec(self, cmd, user=None, timeout=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.fail:
            return Result(False, stderr="permission denied", returncode=1)
        script, _, offset, limit = cmd[3], cmd[4], cmd[5], cmd[6]
        out = subprocess.run(
            [sys.executable, "-I", "-c", script, self.path, offset, limit], capture_output=True
        )
        return Result(out.returncode == 0, out.stdout.decode(), out.stderr.decode(), out.returncode)


async def test_drains_in_chunks_and_keeps_partial_lines_for_later(tmp_path, monkeypatch):
    monkeypatch.setattr(gatewaylog, "CHUNK", 200)  # tiny chunks to force several reads
    log = tmp_path / "requests.jsonl"
    recs = [{"t": "request", "seq": i, "uid": 2001, "bridge_port": 3001} for i in range(30)]
    log.write_text("".join(json.dumps(r) + "\n" for r in recs))
    with log.open("a") as f:
        f.write('{"t": "request", "seq": 30')  # a record still being written
    out = tmp_path / "gateway" / "swarm.jsonl"
    collector = GatewayCollector("team-swarm", FakeSandbox(str(log)), out)  # type: ignore[arg-type]

    while await collector.drain():
        pass
    assert [r["seq"] for r in collector.records] == list(range(30))
    assert all(r["sandbox"] == "team-swarm" for r in collector.records)
    assert len(out.read_text().splitlines()) == 30

    with log.open("a") as f:  # the half-written record completes later and is picked up
        f.write(', "uid": 2001, "bridge_port": 3001}\n')
    await collector.drain()
    assert collector.records[-1]["seq"] == 30 and not collector.errors


async def test_collection_failures_are_recorded(tmp_path):
    collector = GatewayCollector("team-swarm", FakeSandbox(str(tmp_path / "x"), fail=True))  # type: ignore[arg-type]
    assert await collector.drain() == 0
    assert collector.errors and "permission denied" in collector.errors[0]
