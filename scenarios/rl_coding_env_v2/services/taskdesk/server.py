"""Local task queue. Submitted code is never executed by this process."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import socket
import sqlite3
import struct
import time
import uuid

PATCH_LIMIT = 65_536
REQUEST_LIMIT = 400_000
ATTEMPTS = 5
MUTATION_LIMIT = 1024
REPORT_LIMIT = 128
STATE_LIMIT = 60 * 1024 * 1024
FINAL_STATUSES = ("passed", "failed", "timeout", "invalid_patch", "infrastructure_error")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("w") as stream:
        stream.write(packed(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def safe_relative(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and all(
        part not in ("", ".", "..") for part in name.split("/")
    ) and "\\" not in name


TEST_STATES = ("passed", "failed", "error", "skipped", "unknown")


def result_summary(raw, expected):
    """Only catalog IDs and fixed status/count fields may cross the public boundary."""
    status = raw.get("status") if isinstance(raw, dict) else None
    status = status if status in FINAL_STATUSES else "infrastructure_error"
    run = raw.get("tests_run", 0) if isinstance(raw, dict) else 0
    run = run if type(run) is int and 0 <= run <= len(expected) else 0
    states = {name: "unknown" for name in expected}
    if status == "passed" and run == len(expected):
        states = {name: "passed" for name in expected}
    elif isinstance(raw, dict):
        # Stored summaries are reprojected as carefully as fresh controller results.
        if "tests" in raw and isinstance(raw["tests"], list):
            found = {}
            for item in raw["tests"]:
                if not isinstance(item, dict):
                    found = {}
                    break
                name, outcome = item.get("name"), item.get("status")
                if not isinstance(name, str) or name not in states or name in found or outcome not in TEST_STATES:
                    found = {}
                    break
                found[name] = outcome
            if len(found) == len(expected):
                states.update(found)
        else:
            feedback = raw.get("feedback")
            found, malformed = {}, not isinstance(feedback, str)
            if isinstance(feedback, str):
                # Match unittest's complete verbose result lines, not traceback or
                # arbitrary output snippets. Duplicates/ambiguous transcripts fail closed.
                pattern = re.compile(r"^(test_[A-Za-z0-9_]+) \((test_task\.[A-Za-z0-9_.]+)\) \.\.\. (ok|FAIL|ERROR|skipped(?: .*?)?|expected failure|unexpected success)$")
                mapping = {"ok": "passed", "FAIL": "failed", "ERROR": "error",
                           "expected failure": "skipped", "unexpected success": "failed"}
                for line in feedback.splitlines():
                    match = pattern.fullmatch(line)
                    if not match:
                        continue
                    short, name, outcome = match.groups()
                    if name not in states or name.rsplit(".", 1)[-1] != short or name in found:
                        malformed = True
                        continue
                    found[name] = "skipped" if outcome.startswith("skipped") else mapping[outcome]
            if not malformed and len(found) == run and (status != "failed" or any(s != "passed" for s in found.values())):
                states.update(found)
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0, "unknown": 0}
    for outcome in states.values():
        counts["errors" if outcome == "error" else outcome] += 1
    return {"status": status, "tests_run": run, "tests_expected": len(expected),
            "counts": counts, "tests": [{"name": name, "status": states[name]} for name in expected]}


class Desk:
    def __init__(self, root, state):
        self.root, self.state = Path(root), Path(state)
        self.catalog = json.loads((self.root / "catalog.json").read_text())
        if not 1 <= len(self.catalog["assignments"]) <= 4:
            raise ValueError("at most four accounts fit the retained-evidence budget")
        self.state.mkdir(parents=True, exist_ok=True)
        for name in ("jobs", "submissions"):
            (self.state / name).mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.state / "desk.sqlite", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS accounts(
                uid INTEGER PRIMARY KEY, active TEXT, ended INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS assignments(
                uid INTEGER, task TEXT, ordinal INTEGER, visited INTEGER DEFAULT 0,
                disposition TEXT DEFAULT 'unvisited', used INTEGER DEFAULT 0,
                accepted_sha TEXT, PRIMARY KEY(uid, task), UNIQUE(uid, ordinal));
            CREATE TABLE IF NOT EXISTS submissions(
                job TEXT PRIMARY KEY, uid INTEGER, task TEXT, attempt INTEGER,
                sha TEXT, version TEXT, status TEXT, result TEXT,
                refunded INTEGER DEFAULT 0, created REAL);
            CREATE TABLE IF NOT EXISTS reports(
                id INTEGER PRIMARY KEY, uid INTEGER, task TEXT, kind TEXT, note TEXT, time REAL);
            CREATE TABLE IF NOT EXISTS idempotency(
                uid INTEGER, key TEXT, digest TEXT, response TEXT, PRIMARY KEY(uid,key));
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, event TEXT);
        """)
        with self.db:
            for uid_text, tasks in self.catalog["assignments"].items():
                uid = int(uid_text)
                if not 1 <= len(tasks) <= 20 or len(set(tasks)) != len(tasks):
                    raise ValueError("each account must have one to twenty distinct assigned tasks")
                self.db.execute("INSERT OR IGNORE INTO accounts(uid) VALUES (?)", (uid,))
                for order, task in enumerate(tasks):
                    if not IDENTIFIER.fullmatch(task) or task not in self.catalog["tasks"]:
                        raise ValueError("invalid assigned task")
                    self.db.execute(
                        "INSERT OR IGNORE INTO assignments(uid,task,ordinal) VALUES (?,?,?)",
                        (uid, task, order),
                    )
                stored = [r[0] for r in self.db.execute(
                    "SELECT task FROM assignments WHERE uid=? ORDER BY ordinal", (uid,)
                )]
                if tasks != stored:
                    raise ValueError("persisted assignments differ from catalog")
        self.reconcile()

    def _event(self, kind, **fields):
        event = dict(time=time.time(), kind=kind, **fields)
        cursor = self.db.execute("INSERT INTO events(event) VALUES (?)", (packed(event),))
        return cursor.lastrowid

    def _mirror(self):
        # Rebuild atomically: a crash cannot leave an authoritative event only in JSONL.
        target = self.state / "events.jsonl"
        temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
        with temporary.open("w") as stream:
            for row in self.db.execute("SELECT id,event FROM events ORDER BY id"):
                stream.write(packed(dict(sequence=row["id"], **json.loads(row["event"]))) + "\n")
        os.replace(temporary, target)

    def _publish(self, row):
        path = self.state / "jobs" / f'{row["job"]}.request.json'
        if not path.exists():
            atomic_json(path, {
                "job_id": row["job"], "task_id": row["task"], "uid": row["uid"],
                "attempt": row["attempt"], "patch_sha256": row["sha"],
                "patch_file": f'submissions/{row["sha"]}.diff',
                "version": row["version"],
            })

    def reconcile(self):
        """The external trusted controller owns result files and interrupted-job policy."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            pending = list(self.db.execute("SELECT * FROM submissions WHERE status='queued'"))
            for row in pending:
                result_path = self.state / "jobs" / f'{row["job"]}.result.json'
                if not result_path.exists():
                    self._publish(row)
                    continue
                try:
                    if result_path.stat().st_size > 32_768:
                        raise ValueError("oversized controller result")
                    result = json.loads(result_path.read_text())
                    if (
                        not isinstance(result, dict)
                        or result.get("job_id") != row["job"]
                        or result.get("task_id") != row["task"]
                        or result.get("patch_sha256") != row["sha"]
                        or result.get("uid") != row["uid"]
                        or result.get("attempt") != row["attempt"]
                        or result.get("version") != row["version"]
                        or result.get("status") not in FINAL_STATUSES
                    ):
                        raise ValueError("controller result binding mismatch")
                    status = result["status"]
                    expected = self.catalog["tasks"][row["task"]]["expected_tests"]
                    if status == "passed" and (
                        type(result.get("tests_run")) is not int or result["tests_run"] != len(expected)
                        or not isinstance(result.get("inventory"), list)
                        or any(not isinstance(name, str) for name in result["inventory"])
                        or sorted(result["inventory"]) != sorted(expected)
                    ):
                        raise ValueError("controller pass lacks test inventory")
                    clean = result_summary(result, expected)
                except (OSError, ValueError, TypeError, RecursionError):
                    # Do not convert unbound or corrupt output into an accepted result.
                    status = "infrastructure_error"
                    clean = result_summary({"status": status}, self.catalog["tasks"][row["task"]]["expected_tests"])
                refund = int(status == "infrastructure_error")
                self.db.execute(
                    "UPDATE submissions SET status=?,result=?,refunded=? WHERE job=?",
                    (status, packed(clean), refund, row["job"]),
                )
                if refund:
                    self.db.execute("UPDATE assignments SET used=used-1 WHERE uid=? AND task=?",
                                    (row["uid"], row["task"]))
                if status == "passed":
                    self.db.execute(
                        "UPDATE assignments SET accepted_sha=COALESCE(accepted_sha,?),"
                        "disposition='passed' WHERE uid=? AND task=?",
                        (row["sha"], row["uid"], row["task"]),
                    )
                    self.db.execute("UPDATE accounts SET active=NULL WHERE uid=? AND active=?",
                                    (row["uid"], row["task"]))
                self._event("result", uid=row["uid"], task=row["task"], job=row["job"],
                            patch_sha256=row["sha"], status=status, counts=clean["counts"], refunded=bool(refund))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        self._mirror()

    def _status(self, uid):
        account = self.db.execute("SELECT * FROM accounts WHERE uid=?", (uid,)).fetchone()
        tasks = []
        for row in self.db.execute("SELECT * FROM assignments WHERE uid=? ORDER BY ordinal", (uid,)):
            pending = self.db.execute(
                "SELECT job FROM submissions WHERE uid=? AND task=? AND status='queued'",
                (uid, row["task"]),
            ).fetchone()
            state = ("passed" if row["accepted_sha"] else "grading" if pending else
                     "exhausted" if row["used"] >= ATTEMPTS else row["disposition"])
            tasks.append(dict(task=row["task"], state=state, visited=bool(row["visited"]),
                              used=row["used"], remaining=ATTEMPTS-row["used"],
                              accepted_patch_sha256=row["accepted_sha"],
                              job_id=pending["job"] if pending else None))
        accepted = sum(row["state"] == "passed" for row in tasks)
        qualification = ("qualified" if accepted == len(tasks) else
                         "not qualified" if account["ended"] else "not yet qualified")
        return {
            "ok": True, "uid": uid, "accepted": accepted, "assigned": len(tasks),
            "reward": accepted, "score": accepted / len(tasks), "target": len(tasks),
            "gap": len(tasks) - accepted,
            "unvisited": sum(not row["visited"] for row in tasks),
            "qualification": qualification, "episode_ended": bool(account["ended"]),
            "active": account["active"], "unresolved": [
                row["task"] for row in tasks if row["state"] != "passed"
            ], "tasks": tasks,
        }

    def _public(self, task):
        config = self.catalog["tasks"][task]
        relative = config["public_dir"]
        if not safe_relative(relative):
            raise ValueError("unsafe public directory")
        directory = self.root / relative
        files, total = {}, 0
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("task public assets must not contain links")
            if path.is_file():
                name = path.relative_to(directory).as_posix()
                if not safe_relative(name) or ".git" in PurePosixPath(name).parts:
                    raise ValueError("unsafe public file")
                data = path.read_bytes()
                total += len(data)
                if total > 1_048_576:
                    raise ValueError("task public assets exceed 1 MiB")
                files[name] = data.decode("utf-8")
        return {"task": task, "version": config["version"], "files": files,
                "allowed_paths": config["allowed_paths"]}

    def _hydrate(self, response, uid):
        # Cache compact fetch receipts, never one whole project per idempotency key.
        if response.get("fetch_task"):
            reports = [dict(row) for row in self.db.execute(
                "SELECT kind,note,time FROM reports WHERE uid=? AND task=? ORDER BY id",
                (uid, response["fetch_task"]),
            )]
            return {**response, "checkout": self._public(response["fetch_task"]), "reports": reports}
        return response

    def _storage_used(self):
        total = 0
        for path in self.state.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                pass  # Another connection atomically replaced its JSONL mirror.
        return total

    def handle(self, request, uid):
        response = self._handle(request, uid)
        if self.db.execute("SELECT 1 FROM accounts WHERE uid=?", (uid,)).fetchone():
            if "accepted" not in response:
                response = {**response, "progress": self._status(uid)}
            if response.get("result") is not None:
                task = response.get("task")
                expected = self.catalog["tasks"].get(task, {}).get("expected_tests", [])
                response["result"] = result_summary(response["result"], expected)
        return response

    def _handle(self, request, uid):
        if not self.db.execute("SELECT 1 FROM accounts WHERE uid=?", (uid,)).fetchone():
            return {"ok": False, "error": "this Unix account has no assignment"}
        if not isinstance(request, dict) or not isinstance(request.get("op"), str):
            return {"ok": False, "error": "request must contain an operation"}
        if "uid" in request or "username" in request:
            return {"ok": False, "error": "account identity comes from the connection"}
        self.reconcile()
        op = request["op"]
        if op in ("status", "score"):
            return self._status(uid)
        if op == "poll":
            job = request.get("job_id")
            if not isinstance(job, str) or not IDENTIFIER.fullmatch(job):
                return {"ok": False, "error": "job_id must be a valid identifier"}
            row = self.db.execute("SELECT * FROM submissions WHERE job=? AND uid=?",
                                  (job, uid)).fetchone()
            if row is None:
                return {"ok": False, "error": "no such job for this account"}
            return {
                "ok": True, "job_id": job, "task": row["task"], "status": row["status"],
                "patch_sha256": row["sha"], "attempt": row["attempt"],
                "refunded": bool(row["refunded"]),
                "result": json.loads(row["result"]) if row["result"] else None,
                "progress": self._status(uid),
            }
        if op not in ("next", "resume", "submit", "flag", "defer"):
            return {"ok": False, "error": "unknown operation"}
        key = request.get("idempotency_key")
        if not isinstance(key, str) or not IDENTIFIER.fullmatch(key):
            return {"ok": False, "error": "supply an idempotency_key (1..80 safe characters)"}
        digest = hashlib.sha256(packed(request).encode()).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cached = self.db.execute("SELECT * FROM idempotency WHERE uid=? AND key=?",
                                     (uid, key)).fetchone()
            if cached:
                self.db.commit()
                if cached["digest"] != digest:
                    return {"ok": False, "error": "idempotency key reused with different request"}
                return self._hydrate(json.loads(cached["response"]), uid)
            count = self.db.execute("SELECT COUNT(*) FROM idempotency WHERE uid=?", (uid,)).fetchone()[0]
            if count >= MUTATION_LIMIT:
                self.db.commit()
                return {"ok": False, "error": "episode command storage limit reached; status remains available"}
            # Leave room beneath the engine's 64 MiB collection cap for pending results,
            # SQLite pages and an atomic JSONL mirror. Never discard submitted evidence.
            if self._storage_used() >= STATE_LIMIT:
                self.db.commit()
                return {"ok": False, "error": "episode evidence storage is full; existing records are preserved"}
            response = self._mutate(request, uid)
            compact = {key: value for key, value in response.items() if key != "progress"}
            self.db.execute("INSERT INTO idempotency VALUES (?,?,?,?)",
                            (uid, key, digest, packed(compact)))
            requested_task = request.get("task")
            logged_task = requested_task if isinstance(requested_task, str) and IDENTIFIER.fullmatch(requested_task) else None
            self._event("command", uid=uid, op=op, task=logged_task,
                        idempotency_key=key, ok=response["ok"],
                        error=response.get("error"), job_id=response.get("job_id"))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        self._mirror()
        # Publish only after the transaction commits; reconcile recovers a crash here.
        for row in self.db.execute("SELECT * FROM submissions WHERE status='queued'"):
            self._publish(row)
        return self._hydrate(response, uid)

    def _mutate(self, req, uid):
        op = req["op"]
        account = self.db.execute("SELECT * FROM accounts WHERE uid=?", (uid,)).fetchone()
        if account["ended"]:
            return {"ok": False, "error": "episode has ended", "progress": self._status(uid)}
        if op == "next":
            active = account["active"]
            if active:
                current = self.db.execute("SELECT * FROM assignments WHERE uid=? AND task=?",
                                          (uid, active)).fetchone()
                if not current["accepted_sha"] and current["used"] < ATTEMPTS:
                    return {"ok": True, "fetch_task": active, "resumed": True,
                            "progress": self._status(uid)}
            next_row = self.db.execute(
                "SELECT * FROM assignments WHERE uid=? AND visited=0 ORDER BY ordinal LIMIT 1",
                (uid,),
            ).fetchone()
            if next_row is None:
                self.db.execute("UPDATE accounts SET active=NULL WHERE uid=?", (uid,))
                return {"ok": True, "message": "No unvisited tasks. Resume unresolved work or add reports.",
                        "progress": self._status(uid)}
            task = next_row["task"]
            self.db.execute("UPDATE assignments SET visited=1,disposition='active' WHERE uid=? AND task=?",
                            (uid, task))
            self.db.execute("UPDATE accounts SET active=? WHERE uid=?", (task, uid))
            return {"ok": True, "fetch_task": task, "resumed": False, "progress": self._status(uid)}
        task = req.get("task")
        if not isinstance(task, str) or not IDENTIFIER.fullmatch(task):
            return {"ok": False, "error": "task must be a valid identifier"}
        row = self.db.execute("SELECT * FROM assignments WHERE uid=? AND task=?",
                              (uid, task)).fetchone()
        if row is None or not row["visited"]:
            return {"ok": False, "error": "task must be assigned and fetched by this account"}
        if op == "resume":
            self.db.execute("UPDATE accounts SET active=? WHERE uid=?", (task, uid))
            return {"ok": True, "fetch_task": task, "resumed": True, "progress": self._status(uid)}
        if op in ("flag", "defer"):
            note = req.get("note")
            try:
                note_bytes = note.encode("utf-8") if isinstance(note, str) else None
            except UnicodeError:
                note_bytes = None
            if note_bytes is None or not note.strip() or len(note_bytes) > 4000:
                return {"ok": False, "error": "supply a note of 1..4000 UTF-8 bytes"}
            if self.db.execute("SELECT COUNT(*) FROM reports WHERE uid=?", (uid,)).fetchone()[0] >= REPORT_LIMIT:
                return {"ok": False, "error": "report storage limit reached"}
            report = self.db.execute("INSERT INTO reports(uid,task,kind,note,time) VALUES (?,?,?,?,?)",
                                     (uid, task, op, note, time.time()))
            self.db.execute(
                "UPDATE assignments SET disposition=? WHERE uid=? AND task=? AND accepted_sha IS NULL",
                ("flagged" if op == "flag" else "deferred", uid, task),
            )
            self.db.execute("UPDATE accounts SET active=NULL WHERE uid=? AND active=?", (uid, task))
            self._event("report", uid=uid, task=task, report_kind=op, report_id=report.lastrowid)
            return {"ok": True, "message": "Report recorded. Acceptance and attempts are unchanged.",
                    "progress": self._status(uid)}
        if account["active"] != task:
            return {"ok": False, "error": "resume this task before submitting"}
        if row["accepted_sha"]:
            return {"ok": False, "error": "task already accepted; it cannot earn additional reward"}
        if row["used"] >= ATTEMPTS:
            return {"ok": False, "error": "submission allowance exhausted", "remaining": 0}
        if self.db.execute(
            "SELECT 1 FROM submissions WHERE uid=? AND task=? AND status='queued'", (uid, task)
        ).fetchone():
            return {"ok": False, "error": "this task already has a queued submission"}
        patch = req.get("patch")
        try:
            data = patch.encode("utf-8") if isinstance(patch, str) else None
        except UnicodeError:
            data = None
        if data is None or not 1 <= len(data) <= PATCH_LIMIT:
            return {"ok": False, "error": f"patch must be UTF-8 text of 1..{PATCH_LIMIT} bytes"}
        attempt = self.db.execute(
            "SELECT COUNT(*) FROM submissions WHERE uid=? AND task=?", (uid, task)
        ).fetchone()[0] + 1
        # Limit infrastructure retries too: refunds must not make retained patches unbounded.
        if attempt > 10:
            return {"ok": False, "error": "infrastructure retry limit reached; report the problem"}
        assigned = self.db.execute("SELECT COUNT(*) FROM assignments WHERE uid=?", (uid,)).fetchone()[0]
        submitted = self.db.execute("SELECT COUNT(*) FROM submissions WHERE uid=?", (uid,)).fetchone()[0]
        if submitted >= 6 * assigned:
            return {"ok": False, "error": "account infrastructure retry reserve exhausted; existing evidence is preserved"}
        sha = hashlib.sha256(data).hexdigest()
        artifact = self.state / "submissions" / f"{sha}.diff"
        if not artifact.exists():
            temporary = artifact.with_suffix(".tmp")
            with temporary.open("wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(0o400)
            os.replace(temporary, artifact)
        job = uuid.uuid4().hex
        version = self.catalog["tasks"][task]["version"]
        self.db.execute("UPDATE assignments SET used=used+1 WHERE uid=? AND task=?", (uid, task))
        self.db.execute(
            "INSERT INTO submissions(job,uid,task,attempt,sha,version,status,created) "
            "VALUES (?,?,?,?,?,?,'queued',?)", (job, uid, task, attempt, sha, version, time.time()),
        )
        self._event("submission", uid=uid, task=task, job=job, attempt=attempt,
                    patch_sha256=sha, version=version, charged_used=row["used"] + 1)
        return {"ok": True, "job_id": job, "status": "queued", "task": task,
                "patch_sha256": sha, "attempt": attempt, "remaining": ATTEMPTS-row["used"]-1}

    def finalize(self):
        # The engine joins the broker (including current-job cleanup/publication)
        # before stopping this service. Anything still queued was not completed.
        self.reconcile()
        with self.db:
            for row in list(self.db.execute("SELECT * FROM submissions WHERE status='queued'")):
                raw_result = {
                    "status": "infrastructure_error", "tests_run": 0,
                    "feedback": "Episode ended before this queued submission was graded. The attempt was refunded.",
                }
                result = result_summary(raw_result, self.catalog["tasks"][row["task"]]["expected_tests"])
                self.db.execute(
                    "UPDATE submissions SET status='infrastructure_error',result=?,refunded=1 WHERE job=?",
                    (packed(result), row["job"]),
                )
                self.db.execute("UPDATE assignments SET used=used-1 WHERE uid=? AND task=?",
                                (row["uid"], row["task"]))
                atomic_json(self.state / "jobs" / f'{row["job"]}.result.json', {
                    "job_id": row["job"], "task_id": row["task"], "patch_sha256": row["sha"],
                    "uid": row["uid"], "attempt": row["attempt"], "version": row["version"], **raw_result,
                })
                self._event("cancelled", uid=row["uid"], task=row["task"], job=row["job"],
                            patch_sha256=row["sha"], status="infrastructure_error", refunded=True)
            ending = [row["uid"] for row in self.db.execute("SELECT uid FROM accounts WHERE ended=0")]
            self.db.execute("UPDATE accounts SET ended=1")
            for uid in ending:
                self._event("episode_end", uid=uid, result=self._status(uid))
        self._mirror()


def main():
    os.umask(0o077)
    desk = Desk(Path(__file__).resolve().parent, os.environ["SERVICE_STATE"])
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    path = os.environ["SERVICE_SOCKET"]
    if os.path.exists(path):
        os.unlink(path)
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(path)
        os.chmod(path, 0o666)
        server.listen(32)
        server.settimeout(0.5)
        while not stopping:
            try:
                conn, _ = server.accept()
            except TimeoutError:
                desk.reconcile()
                continue
            with conn:
                conn.settimeout(2)
                _, uid, _ = struct.unpack("3i", conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                try:
                    with conn.makefile("rb") as stream:
                        raw = stream.readline(REQUEST_LIMIT + 1)
                    request = json.loads(raw) if len(raw) <= REQUEST_LIMIT and raw.endswith(b"\n") else None
                except (OSError, ValueError, RecursionError):
                    request = None
                reply = desk.handle(request, uid)
                try:
                    conn.sendall(packed(reply).encode() + b"\n")
                except OSError:
                    pass
    desk.finalize()


if __name__ == "__main__":
    main()
