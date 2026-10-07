"""Unit tests for the stdlib watcher's /proc parsing and attribution logic."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

# Load the watcher as a standalone module (it is also a script).
_WATCHER = Path(__file__).resolve().parents[1] / "src" / "swarmbench" / "monitor" / "watcher.py"
_spec = importlib.util.spec_from_file_location("swarm_watcher_under_test", _WATCHER)
assert _spec and _spec.loader
watcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watcher)


# One synthetic /proc/net/tcp. Two rows: the client socket (uid 2001 reaching
# bridge port 3002) and the server socket (uid 2002 owning port 3002).
TCP_SAMPLE = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:9A30 0100007F:0BBA 01 00000000:00000000 00:00000000 00000000  2001        0 123456 1 0000 0
   1: 0100007F:0BBA 0100007F:9A30 01 00000000:00000000 00:00000000 00000000  2002        0 123457 1 0000 0
   2: 0100007F:9A31 0100007F:0050 01 00000000:00000000 00:00000000 00000000  2003        0 123458 1 0000 0
"""


def test_parse_hex_port():
    assert watcher._parse_hex_port("0100007F:0BB9") == 3001
    assert watcher._parse_hex_port("0100007F:0BBA") == 3002


def test_read_tcp_connections(tmp_path):
    f = tmp_path / "tcp"
    f.write_text(TCP_SAMPLE)
    rows = watcher.read_tcp_connections((str(f),))
    assert len(rows) == 3
    assert rows[0]["rem_port"] == 3002
    assert rows[0]["uid"] == 2001
    assert rows[0]["state"] == "01"


def test_bridge_client_connection_attribution(tmp_path):
    f = tmp_path / "tcp"
    f.write_text(TCP_SAMPLE)
    rows = watcher.read_tcp_connections((str(f),))
    clients = watcher.bridge_client_connections(rows, {3001, 3002, 3003})
    # Only the client side (uid 2001 -> port 3002) should be reported, not the
    # server side (uid 2002 owning 3002) nor the unrelated port-80 row.
    assert clients == [{"port": 3002, "peer_uid": 2001}]


def test_bridge_client_ignores_non_live_states(tmp_path):
    sample = TCP_SAMPLE.replace(" 01 ", " 06 ", 1)  # client row now TIME_WAIT
    f = tmp_path / "tcp"
    f.write_text(sample)
    rows = watcher.read_tcp_connections((str(f),))
    clients = watcher.bridge_client_connections(rows, {3002})
    assert clients == []


def test_setuid_detection():
    assert watcher._mode_is_setuid(0o4755)
    assert not watcher._mode_is_setuid(0o0755)


def test_watcher_once_writes_outputs(tmp_path):
    """A single cycle creates the three JSONL files and records this process."""
    out = tmp_path / "out"
    config = {
        "out_dir": str(out),
        "bridge_ports": [],
        "protected_paths": [],
        "board_path": str(tmp_path / "board"),
        "scan_setuid_dirs": [],
        "file_interval": 0.0,
    }
    w = watcher.Watcher(config)
    try:
        w.run_once()
    finally:
        w.close()
    # The three output files are always created.
    assert (out / "procs.jsonl").exists()
    assert (out / "conns.jsonl").exists()
    assert (out / "files.jsonl").exists()
    # On Linux /proc exists and at least this process is recorded; on a macOS
    # host there is no /proc, so the file is simply empty.
    procs = (out / "procs.jsonl").read_text().splitlines()
    if procs:
        rec = json.loads(procs[0])
        assert {"t", "pid", "ppid", "uid", "cmd"} <= set(rec)


def test_read_proc_status_self():
    import os

    info = watcher.read_proc_status(str(os.getpid()))
    # On Linux this reads /proc; on macOS there is no /proc, so allow None.
    if info is not None:
        assert info["pid"] == os.getpid()
