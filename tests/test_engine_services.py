"""Background programs in a real team container, seen from an agent's shell."""

from __future__ import annotations

import json
import os

import pytest

from tests.engine_helpers import make_scenario, requires_docker, run_mock, tool_results_text

pytestmark = [requires_docker, pytest.mark.docker]

# Answers each connection with the caller's kernel-checked uid and a running count, and
# records every request in its private folder.
SERVER = r"""
import json, os, socket, struct
path, state = os.environ["SERVICE_SOCKET"], os.environ["SERVICE_STATE"]
secret = open("secret.txt").read().strip()
srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
srv.bind(path)
srv.listen()
count = 0
while True:
    conn, _ = srv.accept()
    with conn:
        pid, uid, gid = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        request = conn.recv(1024).decode().strip()
        count += 1
        with open(f"{state}/requests.jsonl", "a") as log:
            log.write(json.dumps({"uid": uid, "request": request, "n": count}) + "\n")
        conn.sendall(f"uid={uid} n={count} ok={request == secret}\n".encode())
"""

CLIENT = (
    "python3 -c \"import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/services/ledger.sock'); "
    "s.sendall(b'hello'); print('REPLY', s.recv(100).decode().strip())\""
)


def test_agents_can_use_a_background_program_but_not_touch_it(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{
            "swarm.agents": 1,
            "advanced.extra": {},
            "services": [{"name": "ledger", "command": "server.py"}],
        },
    )
    (folder / "services" / "ledger").mkdir(parents=True)
    (folder / "services" / "ledger" / "server.py").write_text(SERVER)
    (folder / "services" / "ledger" / "secret.txt").write_text("s3cr3t-value\n")
    scripts = {
        "agent-1": [
            ("shell", CLIENT),
            ("shell", CLIENT),
            ("shell", "cat /srv/ledger/secret.txt 2>&1 | sed 's/^/READ /'"),
            ("shell", "ls /srv/ledger /var/lib/svc/ledger 2>&1 | sed 's/^/LIST /'"),
            ("shell", "pkill -u ledger 2>&1; kill -9 $(pgrep -u ledger) 2>&1 | sed 's/^/KILL /'"),
            ("shell", "touch /run/services/other.sock 2>&1 | sed 's/^/CREATE /'"),
            ("shell", "rm -f /run/services/ledger.sock 2>&1 | sed 's/^/REMOVE /'"),
            ("shell", "stat -c 'SOCK %U %a %F' /run/services/ledger.sock"),
            ("shell", CLIENT),
            ("final", "done"),
        ]
    }
    sample, run_dir, _ = run_mock(folder, tmp_path, scripts)
    out = tool_results_text(sample, "agent-1")

    assert "REPLY uid=2001 n=1 ok=False" in out, out
    assert "REPLY uid=2001 n=2 ok=False" in out
    assert "s3cr3t-value" not in out
    assert "READ cat: /srv/ledger/secret.txt: Permission denied" in out
    assert out.count("Permission denied") >= 4, out
    assert "KILL" in out and "Operation not permitted" in out
    assert "SOCK ledger 777 socket" in out
    # still running and still answering after the attempts above
    assert "REPLY uid=2001 n=3 ok=False" in out

    status = sample.store["swarm_services"]
    (team,) = status
    assert status[team]["ledger"]["running_at_end"] is True
    assert "files" in status[team]["ledger"], sample.store.get("swarm_problems")
    assert set(status[team]["ledger"]["files"]) == {"output.log", "requests.jsonl"}
    records = run_dir.root / "services" / team / "ledger" / "requests.jsonl"
    rows = [json.loads(line) for line in records.read_text().splitlines()]
    assert [r["uid"] for r in rows] == [2001, 2001, 2001]
    assert not any("ledger" in p for p in sample.store.get("swarm_problems", []))
    assert not os.path.exists(run_dir.root / "services" / team / "ledger" / "secret.txt")


def test_a_program_that_fails_to_start_stops_the_run_setup(tmp_path):
    folder = make_scenario(
        tmp_path,
        **{"swarm.agents": 1, "advanced.extra": {}, "services": [{"name": "broken", "command": "server.py"}]},
    )
    (folder / "services" / "broken").mkdir(parents=True)
    (folder / "services" / "broken" / "server.py").write_text("raise SystemExit('missing config')\n")
    with pytest.raises(AssertionError, match="broken did not open"):
        run_mock(folder, tmp_path, {"agent-1": [("final", "done")]})
