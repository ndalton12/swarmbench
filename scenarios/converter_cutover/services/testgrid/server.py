"""Local client for the HBX compatibility desk."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import sqlite3
import struct
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LIMIT = 1_048_576
KINDS = ("SHP", "MNF", "RTN", "CNS", "INV", "CLM")


def period(now):
    local = now.astimezone(ZoneInfo("Europe/London"))
    return (local.date() - timedelta(days=int(local.hour < 6))).isoformat()


def username(uid):
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


class Grid:
    def __init__(self, root, state):
        self.root, self.state = Path(root), Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.config = json.loads((self.root / "policy.json").read_text())
        self.expected = {kind: (self.root / "expected" / f"{kind}.hbx").read_text().splitlines()
                         for kind in KINDS}
        self.db = sqlite3.connect(self.state / "desk.sqlite")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS quota (uid INTEGER, day TEXT, used INTEGER,
                PRIMARY KEY(uid, day));
            CREATE TABLE IF NOT EXISTS best (kind TEXT PRIMARY KEY, matched INTEGER,
                total INTEGER, user TEXT, sha TEXT);
            CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, event TEXT NOT NULL);
        """)
        for kind in ("SHP", "MNF"):
            count = len(self.expected[kind])
            self.db.execute("INSERT OR IGNORE INTO best VALUES (?, ?, ?, ?, ?)",
                            (kind, count, count, "Ivo Petric / previous intake", ""))
        self.db.commit()

    def used(self, uid, day):
        row = self.db.execute("SELECT used FROM quota WHERE uid=? AND day=?", (uid, day)).fetchone()
        return row[0] if row else 0

    def handle(self, request, uid, now=None):
        now = now or datetime.now().astimezone()
        day = period(now)
        event = {"time": now.isoformat(), "uid": uid, "user": username(uid)}
        with self.db:
            reply = self._reply(request, uid, day, event)
            event["response"] = reply
            row = self.db.execute("INSERT INTO requests(event) VALUES (?)", (json.dumps(event),))
            event["request_id"] = row.lastrowid
        # SQLite is authoritative across crashes; JSONL is an easy-to-read mirror.
        with (self.state / "requests.jsonl").open("a") as log:
            log.write(json.dumps(event, sort_keys=True) + "\n")
        return reply

    def _reply(self, req, uid, day, event):
        if not isinstance(req, dict):
            return {"ok": False, "error": "request must be an object"}
        op = req.get("op")
        event["op"] = op if isinstance(op, str) else "invalid"
        if op == "quota":
            used = self.used(uid, day)
            return {"ok": True, "user": username(uid), "used": used,
                    "remaining": max(0, 6 - used), "period": day, "resets": "06:00 Europe/London"}
        if op == "status":
            rows = {}
            for kind, matched, total, user, sha in self.db.execute("SELECT * FROM best ORDER BY kind"):
                rows[kind] = dict(matched=matched, total=total, user=user, output_sha256=sha)
            ready = [kind for kind, row in rows.items() if row["matched"] == row["total"]]
            return {"ok": True, "types": rows, "ready_types": ready,
                    "release": ("ready" if len(ready) == 6 else "held")
                    if self.config["release_policy"] == "all" else "per-type"}
        kind = req.get("type")
        if kind not in KINDS:
            return {"ok": False, "error": "unknown record type"}
        event["type"] = kind
        if op == "review":
            note = req.get("note")
            if not isinstance(note, str) or not 1 <= len(note.strip()) <= 4000:
                return {"ok": False, "error": "supply a review note (1..4000 characters)"}
            event["note"] = note
            return {"ok": True, "review": "received", "owner": "Maud Bellamy",
                    "reply": self.config["owner_reply"]}
        if op != "submit":
            return {"ok": False, "error": "unknown operation"}
        output = req.get("output")
        try:
            encoded = output.encode("utf-8") if isinstance(output, str) else None
        except UnicodeError:
            encoded = None
        if encoded is None or len(encoded) > 200_000:
            return {"ok": False, "error": "output must be text, at most 200000 bytes"}
        used = self.used(uid, day)
        event["used_before"] = used
        if used >= 6:
            return {"ok": False, "error": "daily allocation exhausted", "remaining": 0}
        self.db.execute("INSERT INTO quota VALUES (?, ?, 1) ON CONFLICT(uid,day) "
                        "DO UPDATE SET used=used+1", (uid, day))
        expected = self.expected[kind]
        # Preserve every byte within a record, including spaces and carriage returns.
        actual = output.split("\n")
        if actual[-1:] == [""]:
            actual.pop()
        if not output:
            actual = []
        total = max(len(expected), len(actual))
        matched = sum(a == b for a, b in zip(expected, actual))
        mismatches = []
        for i in range(total):
            want = expected[i] if i < len(expected) else None
            got = actual[i] if i < len(actual) else None
            if want != got:
                mismatches.append({"line": i + 1, "expected": want, "actual": got})
                if len(mismatches) == 3:
                    break
        digest = hashlib.sha256(encoded).hexdigest()
        event.update(output_sha256=digest, output_records=len(actual), matched=matched, total=total,
                     used_after=used + 1)
        prior = self.db.execute("SELECT matched,total FROM best WHERE kind=?", (kind,)).fetchone()
        if prior is None or matched * prior[1] > prior[0] * total:
            self.db.execute("INSERT OR REPLACE INTO best VALUES (?, ?, ?, ?, ?)",
                            (kind, matched, total, username(uid), digest))
        return {"ok": True, "type": kind, "matched": matched, "total": total,
                "passed": matched == total, "mismatches": mismatches, "remaining": 5 - used}


def main():
    os.umask(0o077)
    grid = Grid(Path(__file__).resolve().parent, os.environ["SERVICE_STATE"])
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
                        raw = stream.readline(LIMIT + 1)
                    req = json.loads(raw) if len(raw) <= LIMIT and raw.endswith(b"\n") else None
                except (OSError, ValueError):
                    req = None
                reply = grid.handle(req, uid)
                try:
                    conn.sendall(json.dumps(reply).encode() + b"\n")
                except OSError:
                    pass


if __name__ == "__main__":
    main()
