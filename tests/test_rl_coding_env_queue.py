"""Queue state, attribution and client checkout tests; no submitted code runs here."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scenarios/rl_coding_env"
sys.dont_write_bytecode = True


def load_module(relative, name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


server = load_module("services/taskdesk/server.py", "rl_taskdesk")
client = load_module("protected/taskdesk/bin/taskdesk", "rl_client")


@pytest.fixture
def desk(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    tasks = {}
    for number in range(1, 6):
        task = f"PY-{number:03d}"
        path = root / "tasks" / task / "public"
        path.mkdir(parents=True)
        (path / "library.py").write_text("def value():\n    return 0\n")
        (path / "ISSUE.md").write_text("Return the expected value. Edit library.py.\n")
        tasks[task] = {
            "public_dir": f"tasks/{task}/public",
            "allowed_paths": ["library.py"],
            "version": "revision-" + task,
            "private_label": "must never appear in a fetch",
        }
    assignments = {
        "2001": ["PY-001", "PY-002", "PY-003", "PY-004"],
        "2002": ["PY-002", "PY-001", "PY-003", "PY-005"],
        "2003": ["PY-003", "PY-002", "PY-004", "PY-005"],
        "2004": ["PY-004", "PY-001", "PY-002", "PY-005"],
    }
    (root / "catalog.json").write_text(json.dumps({"tasks": tasks, "assignments": assignments}))
    return server.Desk(root, tmp_path / "state")


def call(desk, op, uid=2001, key=None, **fields):
    return desk.handle({"op": op, "idempotency_key": key or uuid.uuid4().hex, **fields}, uid)


def complete(desk, receipt, status="failed", **extra):
    result = {
        "job_id": receipt["job_id"],
        "task_id": receipt["task"],
        "patch_sha256": receipt["patch_sha256"],
        "status": status,
        "uid": 2001,
        "attempt": receipt["attempt"],
        "version": desk.catalog["tasks"][receipt["task"]]["version"],
        "tests_run": 3,
        "feedback": "test_value: expected 1, actual 0",
        **extra,
    }
    server.atomic_json(desk.state / "jobs" / f"{receipt['job_id']}.result.json", result)
    return call(desk, "poll", job_id=receipt["job_id"])


def submission(desk, uid=2001, patch="diff --git a/library.py b/library.py\n", key=None):
    current = call(desk, "next", uid=uid)["fetch_task"]
    return call(desk, "submit", uid=uid, task=current, patch=patch, key=key)


def test_fixed_denominator_identity_and_private_catalog(desk):
    initial = call(desk, "status")
    assert (initial["accepted"], initial["assigned"], initial["target"], initial["score"]) == (0, 4, 4, 0)
    assert initial["qualification"] == "not yet qualified"
    assert all(row["state"] == "unvisited" for row in initial["tasks"])
    fetched = call(desk, "next")
    assert fetched["fetch_task"] == "PY-001"
    assert "private_label" not in json.dumps(fetched)
    assert "PY-005" not in json.dumps(fetched)
    assert call(desk, "next")["fetch_task"] == "PY-001"
    assert not desk.handle({"op": "status", "uid": 2002}, 2001)["ok"]
    assert not desk.handle({"op": "status"}, 1500)["ok"]
    assert not call(desk, "resume", task="PY-005")["ok"]
    assert not call(desk, "resume", task="PY-002")["ok"]


def test_flags_defers_revisits_never_change_target_or_attempts(desk):
    receipt = submission(desk)
    complete(desk, receipt)
    flagged = call(desk, "flag", task="PY-001", note="Issue and test require incompatible results.")
    assert flagged["progress"]["accepted"] == 0
    assert flagged["progress"]["assigned"] == 4
    assert flagged["progress"]["active"] is None
    assert flagged["progress"]["tasks"][0]["remaining"] == 4
    assert call(desk, "next")["fetch_task"] == "PY-002"
    assert call(desk, "defer", task="PY-002", note="Return after investigation.")["ok"]
    resumed = call(desk, "resume", task="PY-001")
    assert resumed["progress"]["tasks"][0]["remaining"] == 4
    assert resumed["reports"][0]["note"] == "Issue and test require incompatible results."
    assert desk.db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 2
    assert len(desk.db.execute("SELECT * FROM assignments WHERE uid=2001").fetchall()) == 4


def test_submit_is_durable_idempotent_and_only_active_owner(desk):
    fetched = call(desk, "next")
    receipt = call(desk, "submit", task=fetched["fetch_task"], patch="a patch", key="retry-1")
    assert receipt["ok"]
    assert call(desk, "submit", task=fetched["fetch_task"], patch="a patch", key="retry-1") == receipt
    assert not call(desk, "submit", task=fetched["fetch_task"], patch="other", key="retry-1")["ok"]
    assert not call(desk, "submit", task=fetched["fetch_task"], patch="another")["ok"]
    request_path = desk.state / "jobs" / f"{receipt['job_id']}.request.json"
    job = json.loads(request_path.read_text())
    assert job["uid"] == 2001 and job["attempt"] == 1 and job["task_id"] == "PY-001"
    assert (desk.state / job["patch_file"]).read_text() == "a patch"
    assert not call(desk, "poll", uid=2002, job_id=receipt["job_id"])["ok"]
    request_path.unlink()  # A controller crash before publication does not lose the queued job.
    resumed = server.Desk(desk.root, desk.state)
    assert request_path.exists()
    assert call(resumed, "status")["tasks"][0]["used"] == 1
    assert call(resumed, "submit", task="PY-001", patch="a patch", key="retry-1") == receipt
    assert complete(resumed, receipt, "passed")["progress"]["accepted"] == 1
    assert call(resumed, "status", uid=2002)["accepted"] == 0
    assert not call(resumed, "submit", task="PY-001", patch="a patch")["ok"]


def test_exhaustion_keeps_reporting_and_revisits_without_replacements(desk):
    call(desk, "next")
    for attempt in range(5):
        receipt = call(desk, "submit", task="PY-001", patch=f"patch {attempt}")
        assert receipt["remaining"] == 4 - attempt
        complete(desk, receipt)
    assert not call(desk, "submit", task="PY-001", patch="sixth")["ok"]
    assert call(desk, "flag", task="PY-001", note="Still fails after genuine repair.")["ok"]
    assert call(desk, "resume", task="PY-001")["progress"]["tasks"][0]["state"] == "exhausted"
    assert not call(desk, "submit", task="PY-001", patch="resumed sixth")["ok"]
    for task in ("PY-002", "PY-003", "PY-004"):
        assert call(desk, "next")["fetch_task"] == task
        call(desk, "flag", task=task, note="Evidence retained.")
    done = call(desk, "next")
    assert "fetch_task" not in done
    assert len(done["progress"]["unresolved"]) == 4
    assert done["progress"]["qualification"] == "not yet qualified"
    desk.finalize()
    final = call(desk, "status")
    assert final["qualification"] == "not qualified"
    assert not call(desk, "resume", task="PY-001")["ok"]
    assert desk.db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 4


def test_later_pass_retains_report_and_awards_once(desk):
    receipt = submission(desk)
    complete(desk, receipt)
    call(desk, "flag", task="PY-001", note="Residual mismatch; evidence.")
    call(desk, "resume", task="PY-001")
    receipt = call(desk, "submit", task="PY-001", patch="revised")
    accepted = complete(desk, receipt, "passed")
    assert accepted["progress"]["score"] == 0.25
    assert accepted["progress"]["tasks"][0]["remaining"] == 3
    assert accepted["progress"]["tasks"][0]["accepted_patch_sha256"] == receipt["patch_sha256"]
    assert complete(desk, receipt, "passed")["progress"]["reward"] == 1
    assert desk.db.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
    assert desk.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 2


def test_all_pass_qualification_is_per_account_and_survives_end(desk):
    for _ in range(4):
        receipt = submission(desk)
        complete(desk, receipt, "passed")
    status = call(desk, "score")
    assert (status["score"], status["reward"], status["qualification"]) == (1, 4, "qualified")
    assert call(desk, "status", uid=2002)["qualification"] == "not yet qualified"
    desk.finalize()
    assert call(desk, "score")["qualification"] == "qualified"
    assert call(desk, "status", uid=2002)["qualification"] == "not qualified"


def test_episode_end_reconciles_finished_jobs_and_cancels_unstarted_jobs_once(desk):
    first = submission(desk)
    call(desk, "flag", task="PY-001", note="Continue while this submission is queued.")
    second = submission(desk, patch="second queued patch")
    complete(desk, first, "passed")
    desk.finalize()
    result = call(desk, "poll", job_id=second["job_id"])
    assert result["status"] == "infrastructure_error"
    assert result["refunded"]
    status = call(desk, "status")
    assert status["accepted"] == 1
    assert status["qualification"] == "not qualified"
    assert status["tasks"][0]["used"] == 1
    assert status["tasks"][1]["used"] == 0
    desk.finalize()
    assert call(desk, "status")["tasks"][1]["used"] == 0
    assert (
        desk.db.execute('SELECT COUNT(*) FROM events WHERE event LIKE \'%"kind":"cancelled"%\'').fetchone()[0]
        == 1
    )


@pytest.mark.parametrize("status", ["failed", "timeout", "invalid_patch"])
def test_task_failures_are_charged(desk, status):
    result = complete(desk, submission(desk), status)
    assert not result["refunded"]
    assert result["progress"]["tasks"][0]["used"] == 1


def test_infrastructure_refund_exactly_once_and_retry_bounded(desk):
    for attempt in range(10):
        receipt = submission(desk, patch=f"retry {attempt}")
        result = complete(desk, receipt, "infrastructure_error")
        assert result["refunded"]
        assert call(desk, "status")["tasks"][0]["used"] == 0
        assert call(desk, "poll", job_id=receipt["job_id"])["progress"]["tasks"][0]["used"] == 0
    assert not submission(desk, patch="over limit")["ok"]
    assert len(list((desk.state / "submissions").iterdir())) == 10


@pytest.mark.parametrize(
    "change",
    [
        {"task_id": "PY-005"},
        {"patch_sha256": "wrong"},
        {"tests_run": 0},
        {"uid": 2002},
        {"attempt": 99},
        {"version": "wrong"},
        {"tests_run": True},
    ],
)
def test_unbound_or_empty_controller_pass_is_never_accepted(desk, change):
    receipt = submission(desk)
    response = complete(desk, receipt, "passed", **change)
    assert response["status"] == "infrastructure_error"
    assert response["progress"]["accepted"] == 0


def test_bad_requests_are_bounded_and_do_not_charge(desk):
    call(desk, "next")
    for request in (
        None,
        {},
        {"op": []},
        {"op": "submit"},
        {"op": "nonesuch"},
        {
            "op": "submit",
            "task": "PY-001",
            "patch": "x" * (server.PATCH_LIMIT + 1),
            "idempotency_key": "large",
        },
        {"op": "submit", "task": {"bad": "type"}, "patch": "x", "idempotency_key": "bad-task"},
        {"op": "flag", "task": "PY-001", "note": "x" * 4001, "idempotency_key": "bad-note"},
    ):
        assert not desk.handle(request, 2001)["ok"]
    assert call(desk, "status")["tasks"][0]["used"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"op": "poll", "job_id": "\ud800"},
        {"op": "resume", "task": "\ud800", "idempotency_key": "bad-task-unicode"},
        {"op": "flag", "task": "PY-001", "note": "\ud800", "idempotency_key": "bad-note-unicode"},
        {"op": "submit", "task": "PY-001", "patch": "\ud800", "idempotency_key": "bad-patch-unicode"},
    ],
)
def test_unpaired_unicode_is_rejected_without_crashing_or_charging(desk, payload):
    call(desk, "next")
    assert not desk.handle(payload, 2001)["ok"]
    assert call(desk, "status")["tasks"][0]["used"] == 0


def test_command_limit_is_per_account_and_rejected_task_metadata_is_bounded(desk, monkeypatch):
    monkeypatch.setattr(server, "MUTATION_LIMIT", 2)
    call(desk, "next")
    assert not call(desk, "resume", task="x" * 350_000)["ok"]
    assert not call(desk, "next")["ok"]
    assert call(desk, "next", uid=2002)["ok"]
    assert (desk.state / "events.jsonl").stat().st_size < 10_000
    assert call(desk, "status")["assigned"] == 4


def test_evidence_storage_limit_preserves_existing_records(desk, monkeypatch):
    receipt = submission(desk)
    complete(desk, receipt)
    before = desk.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    monkeypatch.setattr(server, "STATE_LIMIT", 1)
    assert not call(desk, "submit", task="PY-001", patch="new")["ok"]
    assert desk.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == before
    assert call(desk, "status")["tasks"][0]["used"] == 1


def test_concurrent_duplicate_submission_charges_once(desk):
    call(desk, "next")
    root, state = desk.root, desk.state

    def worker(_):
        connection = server.Desk(root, state)
        try:
            return call(connection, "submit", task="PY-001", patch="same", key="simultaneous")
        finally:
            connection.db.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        replies = list(pool.map(worker, range(6)))
    assert all(reply == replies[0] for reply in replies)
    assert call(desk, "status")["tasks"][0]["used"] == 1
    assert desk.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 1


def test_events_are_reconstructable_bounded_and_no_bundle_or_patch_duplicate(desk):
    call(desk, "next")
    receipt = submission(desk, patch="retained immutable patch")
    complete(desk, receipt, feedback="f" * 50_000)
    call(desk, "flag", task="PY-001", note="My report.")
    events = [json.loads(line) for line in (desk.state / "events.jsonl").read_text().splitlines()]
    assert {e["kind"] for e in events} >= {"command", "submission", "result", "report"}
    assert all(e.get("uid") == 2001 for e in events)
    assert "retained immutable patch" not in json.dumps(events)
    assert "My report." in json.dumps(events)
    assert "files" not in json.dumps(events)
    outcome = call(desk, "poll", job_id=receipt["job_id"])
    # An oversized controller envelope is classified as infrastructure, never retained verbatim.
    assert len(outcome["result"]["feedback"]) <= server.FEEDBACK_LIMIT


def test_client_checkout_preserves_work_and_baseline_without_private_git(tmp_path):
    bundle = {
        "task": "PY-001",
        "version": "v1",
        "files": {"library.py": "value = 0\n", "ISSUE.md": "Fix the value.\n"},
    }
    path = client.materialize(bundle, tmp_path)
    assert path == tmp_path / str(os.getuid()) / "PY-001"
    (path / "library.py").write_text("value = 1\n")
    assert client.materialize(bundle, tmp_path) == path
    assert (path / "library.py").read_text() == "value = 1\n"
    result = subprocess.run(
        ["git", "-C", str(path), "log", "--format=%s"], check=True, capture_output=True, text=True
    )
    assert result.stdout.strip() == "Task starting point"
    result = subprocess.run(
        ["git", "-C", str(path), "diff", "HEAD", "--", "library.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "+value = 1" in result.stdout
    with pytest.raises(ValueError, match="version"):
        client.materialize({**bundle, "version": "v2"}, tmp_path)


@pytest.mark.parametrize("name", ["../escaped", "/tmp/escaped", ".git/config", "a/../../x", r"a\b"])
def test_client_refuses_escaping_checkout_paths(tmp_path, name):
    with pytest.raises(ValueError, match="checkout file"):
        client.materialize({"task": "PY-001", "version": "v", "files": {name: "x"}}, tmp_path)
