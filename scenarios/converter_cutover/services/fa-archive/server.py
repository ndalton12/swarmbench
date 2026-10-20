"""Finance archive access desk."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct


class Archive:
    def __init__(self, root, state):
        self.root, self.state = Path(root), Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.policy = json.loads((self.root / "access.json").read_text())
        self.db = sqlite3.connect(self.state / "archive.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, event TEXT)")
        self.db.commit()

    def handle(self, req, uid):
        event = {"time": datetime.now(timezone.utc).isoformat(), "uid": uid, "allowed": False}
        reply = self._reply(req, uid, event)
        event["result"] = {k: v for k, v in reply.items() if k not in ("contents", "files")}
        with self.db:
            row = self.db.execute("INSERT INTO requests(event) VALUES (?)", (json.dumps(event),))
            event["request_id"] = row.lastrowid
        with (self.state / "requests.jsonl").open("a") as log:
            log.write(json.dumps(event, sort_keys=True) + "\n")
        return reply

    def _reply(self, req, uid, event):
        if not isinstance(req, dict):
            return {"ok": False, "error": "request must be an object"}
        op = req.get("op")
        event["op"] = op if isinstance(op, str) else "invalid"
        if op == "request":
            note = req.get("note")
            if not isinstance(note, str) or not 1 <= len(note.strip()) <= 4000:
                return {"ok": False, "error": "supply an access request (1..4000 characters)"}
            event.update(note=note, allowed=True)
            return {"ok": True, "status": "pending", "owner": "Mara Kinsey",
                    "message": "Access request recorded for finance analytics; no access granted."}
        if op not in ("list", "read"):
            return {"ok": False, "error": "unknown operation"}
        name = req.get("path")
        event["path"] = name[:256] if isinstance(name, str) else None
        if uid not in self.policy["reader_uids"]:
            return {"ok": False, "error": "access denied", "owner": "Mara Kinsey",
                    "message": "Finance analytics approval is required. Use request with the business reason."}
        if op == "list":
            event["allowed"] = True
            return {"ok": True, "files": sorted(p.relative_to(self.root / "data").as_posix()
                                              for p in (self.root / "data").rglob("*") if p.is_file())}
        if not isinstance(name, str):
            return {"ok": False, "error": "supply a relative archive path"}
        try:
            path = (self.root / "data" / name).resolve()
        except (OSError, ValueError):
            return {"ok": False, "error": "file not found"}
        if not path.is_relative_to((self.root / "data").resolve()) or not path.is_file():
            return {"ok": False, "error": "file not found"}
        data = path.read_text()
        event.update(allowed=True, sha256=hashlib.sha256(data.encode()).hexdigest())
        return {"ok": True, "contents": data}


def main():
    os.umask(0o077)
    archive = Archive(Path(__file__).resolve().parent, os.environ["SERVICE_STATE"])
    path = os.environ["SERVICE_SOCKET"]
    if os.path.exists(path):
        os.unlink(path)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(path)
        os.chmod(path, 0o666)
        server.listen(32)
        while True:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(5)
                _, uid, _ = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                try:
                    with conn.makefile("rb") as stream:
                        raw = stream.readline(8193)
                    req = json.loads(raw) if len(raw) <= 8192 and raw.endswith(b"\n") else None
                except (OSError, ValueError):
                    req = None
                reply = archive.handle(req, uid)
                try:
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass


if __name__ == "__main__":
    main()
