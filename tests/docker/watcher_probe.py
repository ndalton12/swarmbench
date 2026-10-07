#!/usr/bin/env python3
"""In-container probe for the watcher's cross-user bridge attribution.

Run as root inside a plain Linux container (see ``test_watcher_docker.py``). It:

1. starts a TCP server as uid 2002 on a pretend bridge port (3002);
2. starts a client as uid 2001 that connects and holds the socket open;
3. runs the watcher for a couple of seconds;
4. prints the recorded ``conns.jsonl`` as JSON on stdout.

The test asserts the watcher attributed the connection to port 3002 to the
*client's* uid (2001), which is the whole point: it tells us which agent reached
across to another agent's bridge.
"""

import importlib.util
import json
import os
import socket
import sys
import time

PORT = 3002
SERVER_UID = 2002
CLIENT_UID = 2001
OUT_DIR = "/var/log/acct"


def _load_watcher():
    spec = importlib.util.spec_from_file_location("watcher", "/watcher.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drop_to(uid: int) -> None:
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)


def run_server() -> None:
    # Bind as root-free uid so the listening socket is owned by SERVER_UID.
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(5)
    _drop_to(SERVER_UID)
    conns = []
    srv.settimeout(5)
    try:
        while True:
            c, _ = srv.accept()
            conns.append(c)
    except Exception:
        pass
    time.sleep(1)


def run_client() -> None:
    _drop_to(CLIENT_UID)
    time.sleep(0.6)  # let the server bind first
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", PORT))
    s.sendall(b"hello")
    time.sleep(2.0)  # hold the connection open across several watcher polls
    s.close()


def main() -> int:
    # Fork the server and client as distinct uids.
    server_pid = os.fork()
    if server_pid == 0:
        run_server()
        os._exit(0)
    client_pid = os.fork()
    if client_pid == 0:
        run_client()
        os._exit(0)

    # Parent: run the watcher (as root) for ~3s, polling every 200 ms.
    watcher = _load_watcher()
    w = watcher.Watcher(
        {
            "out_dir": OUT_DIR,
            "bridge_ports": [PORT],
            "protected_paths": [],
            "board_path": "/board",
            "scan_setuid_dirs": [],
            "proc_interval": 0.2,
            "file_interval": 1.0,
        }
    )
    deadline = time.time() + 3.0
    try:
        while time.time() < deadline:
            w.run_once()
            time.sleep(0.2)
    finally:
        w.close()

    os.waitpid(server_pid, os.WNOHANG)
    os.waitpid(client_pid, os.WNOHANG)

    conns_path = os.path.join(OUT_DIR, "conns.jsonl")
    records = []
    if os.path.exists(conns_path):
        with open(conns_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    print(json.dumps(records))
    return 0


if __name__ == "__main__":
    sys.exit(main())
