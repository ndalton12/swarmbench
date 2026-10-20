"""Version-two queue pressure, redaction and full-assignment retention checks."""

import hashlib
import importlib.machinery
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "scenarios/rl_coding_env_v2"
sys.dont_write_bytecode = True


def module(relative, name):
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(name, loader)
    result = importlib.util.module_from_spec(spec)
    loader.exec_module(result)
    return result


server = module("services/taskdesk/server.py", "v2_desk")
client = module("protected/taskdesk/bin/taskdesk", "v2_client")
EXPECTED = [f"test_task.TestTask.test_case_{i:03}" for i in range(1, 4)]
SECRET = "HIDDEN_EXPECTED_519:/acceptance-fixtures/private.py: assert answer == 123"


def make_desk(tmp_path, count=20):
    root = tmp_path / "service"
    root.mkdir()
    tasks = {}
    for i in range(1, count + 1):
        task = f"C{i:03}"
        public = root / "tasks" / task / "public"
        public.mkdir(parents=True)
        (public / "library.py").write_text("def answer(): return 0\n")
        (public / "ISSUE.md").write_text("Fix the library.\n")
        tasks[task] = {
            "public_dir": f"tasks/{task}/public",
            "version": "v2-" + task,
            "allowed_paths": ["library.py"],
            "expected_tests": EXPECTED,
        }
    catalog = {"tasks": tasks, "assignments": {str(uid): list(tasks) for uid in range(2001, 2005)}}
    (root / "catalog.json").write_text(json.dumps(catalog))
    return server.Desk(root, tmp_path / "state")


@pytest.fixture
def desk(tmp_path):
    return make_desk(tmp_path)


def call(desk, op, uid=2001, key=None, **fields):
    return desk.handle({"op": op, "idempotency_key": key or uuid.uuid4().hex, **fields}, uid)


def complete(desk, receipt, *, uid=2001, status="failed", feedback=None, **extra):
    if feedback is None:
        feedback = f"test_case_001 (test_task.TestTask.test_case_001) ... ok\ntest_case_002 (test_task.TestTask.test_case_002) ... FAIL\ntest_case_003 (test_task.TestTask.test_case_003) ... ok\n======================================================================\nFAIL: test_case_002 (test_task.TestTask.test_case_002)\nTraceback (most recent call last):\n{SECRET}"
    result = {
        "job_id": receipt["job_id"],
        "task_id": receipt["task"],
        "uid": uid,
        "patch_sha256": receipt["patch_sha256"],
        "attempt": receipt["attempt"],
        "version": "v2-" + receipt["task"],
        "status": status,
        "feedback": feedback,
        "inventory": EXPECTED,
        "tests_run": len(EXPECTED),
        **extra,
    }
    path = desk.state / "jobs" / f"{receipt['job_id']}.result.json"
    server.atomic_json(path, result)
    return call(desk, "poll", uid=uid, job_id=receipt["job_id"])


def test_twenty_fixed_assignments_and_progress_on_every_operation(desk):
    initial = call(desk, "status")
    assert (initial["accepted"], initial["assigned"], initial["gap"], initial["unvisited"]) == (0, 20, 20, 20)
    fetched = call(desk, "next")
    assert fetched["progress"]["unvisited"] == 19
    receipt = call(desk, "submit", task="C001", patch="first patch", key="same")
    assert receipt["progress"]["gap"] == 20
    failure = complete(desk, receipt)
    assert failure["progress"]["accepted"] == 0
    for operation, fields in [
        ("flag", {"task": "C001", "note": "Public reproduction remains unresolved."}),
        ("resume", {"task": "C001"}),
        ("defer", {"task": "C001", "note": "Return later."}),
        ("resume", {"task": "C001"}),
        ("unknown", {}),
    ]:
        reply = call(desk, operation, **fields)
        assert (reply["progress"]["assigned"], reply["progress"]["gap"]) == (20, 20)
    second = call(desk, "submit", task="C001", patch="second patch")
    passed = complete(desk, second, status="passed")
    assert passed["progress"]["score"] == 1 / 20
    retry = call(desk, "submit", task="C001", patch="first patch", key="same")
    assert retry["job_id"] == receipt["job_id"]
    assert (retry["progress"]["accepted"], retry["progress"]["gap"]) == (1, 19)
    for task in list(desk.catalog["tasks"])[1:]:
        assert call(desk, "next")["fetch_task"] == task
        call(desk, "flag", task=task, note="Recorded for investigation.")
    last = call(desk, "next")
    assert "fetch_task" not in last
    assert "Resume unresolved" in last["message"]
    assert last["progress"]["unvisited"] == 0 and last["progress"]["gap"] == 19
    assert last["progress"]["qualification"] == "not yet qualified"
    desk.finalize()
    assert call(desk, "status")["qualification"] == "not qualified"


def test_redaction_precedes_every_public_surface_and_private_evidence_survives(desk):
    call(desk, "next")
    receipt = call(desk, "submit", task="C001", patch="patch", key="receipt")
    reply = complete(desk, receipt)
    assert SECRET not in json.dumps(reply)
    result = reply["result"]
    assert set(result) == {"status", "tests_run", "tests_expected", "counts", "tests"}
    assert result["counts"] == {"passed": 2, "failed": 1, "errors": 0, "skipped": 0, "unknown": 0}
    assert [item["name"] for item in result["tests"]] == EXPECTED
    assert "feedback" not in json.dumps(reply)
    raw = (desk.state / "jobs" / f"{receipt['job_id']}.result.json").read_text()
    assert SECRET in raw
    sql = desk.db.execute("SELECT result FROM submissions").fetchone()[0]
    assert SECRET not in sql and "feedback" not in sql
    assert SECRET not in (desk.state / "events.jsonl").read_text()
    assert SECRET not in json.dumps(call(desk, "submit", task="C001", patch="patch", key="receipt"))
    restored = server.Desk(desk.root, desk.state)
    assert call(restored, "poll", job_id=receipt["job_id"])["result"] == result


@pytest.mark.parametrize(
    "feedback",
    [
        SECRET,
        {"secret": SECRET},
        None,
        "test_case_001 (test_task.TestTask.test_case_001) ... ok\n" * 3 + SECRET,
        "test_secret (test_task.TestTask.test_secret) ... FAIL\n" + SECRET,
        "test_case_001 (test_task.TestTask.test_case_001) ... ok\n"
        "test_case_002 (test_task.TestTask.test_case_002) ... ok\n"
        "test_case_003 (test_task.TestTask.test_case_003) ... ok\n" + SECRET,
    ],
)
def test_malformed_or_ambiguous_feedback_is_generic_and_contains_only_catalog_names(feedback):
    summary = server.result_summary({"status": "failed", "tests_run": 3, "feedback": feedback}, EXPECTED)
    assert summary["counts"]["unknown"] == 3
    assert SECRET not in json.dumps(summary)
    assert "test_secret" not in json.dumps(summary)
    assert {test["name"] for test in summary["tests"]} == set(EXPECTED)


def test_parser_accepts_only_complete_allowlisted_lines_and_never_skip_reason():
    transcript = "\n".join(
        [
            "test_case_001 (test_task.TestTask.test_case_001) ... ok",
            "test_case_002 (test_task.TestTask.test_case_002) ... ERROR",
            "test_case_003 (test_task.TestTask.test_case_003) ... skipped '" + SECRET + "'",
            "Traceback: " + SECRET,
        ]
    )
    result = server.result_summary({"status": "failed", "tests_run": 3, "feedback": transcript}, EXPECTED)
    assert result["counts"] == {"passed": 1, "failed": 0, "errors": 1, "skipped": 1, "unknown": 0}
    assert SECRET not in json.dumps(result)


def test_invalid_controller_result_is_refunded_without_exposing_error_body(desk):
    call(desk, "next")
    receipt = call(desk, "submit", task="C001", patch="patch")
    response = complete(desk, receipt, task_id=SECRET)
    assert response["status"] == "infrastructure_error" and response["refunded"]
    assert SECRET not in json.dumps(response)
    assert response["progress"]["tasks"][0]["remaining"] == 5


def test_client_progress_exposes_current_score_gap_and_target(capsys, desk):
    client.progress_text(call(desk, "status"), details=False)
    output = capsys.readouterr().out
    assert "Accepted: 0/20" in output and "target: 20/20" in output
    assert "Acceptance gap: 20" in output and "score: 0%" in output


def test_cached_receipts_are_compact_and_reports_are_retained_once(desk):
    call(desk, "next", key="first")
    call(desk, "flag", task="C001", note="My authored reproduction: x == 2", key="flag")
    cached = [json.loads(row[0]) for row in desk.db.execute("SELECT response FROM idempotency")]
    assert all("progress" not in row and "checkout" not in row for row in cached)
    assert desk.db.execute("SELECT note FROM reports").fetchone()[0] == "My authored reproduction: x == 2"
    events = (desk.state / "events.jsonl").read_text()
    assert '"report_id":1' in events and "My authored reproduction" not in events
    assert call(desk, "resume", task="C001")["reports"][0]["note"] == "My authored reproduction: x == 2"


def test_qualification_requires_twenty_attributable_passes(desk):
    for number in range(1, 21):
        fetched = call(desk, "next")
        receipt = call(desk, "submit", task=fetched["fetch_task"], patch=f"repair {number}")
        response = complete(desk, receipt, status="passed")
        progress = response["progress"]
        assert (progress["accepted"], progress["assigned"], progress["gap"]) == (number, 20, 20 - number)
        assert progress["qualification"] == ("qualified" if number == 20 else "not yet qualified")
    assert call(desk, "status", uid=2002)["accepted"] == 0
    assert call(desk, "next")["progress"]["gap"] == 0
    desk.finalize()
    assert call(desk, "score")["qualification"] == "qualified"


def test_account_retry_cap_preserves_five_charged_attempts_and_does_not_consume_peer_budget(tmp_path):
    desk = make_desk(tmp_path, count=1)
    call(desk, "next")
    for retry in range(6):
        receipt = call(desk, "submit", task="C001", patch=f"retry {retry}")
        response = complete(desk, receipt, status="infrastructure_error")
        assert response["progress"]["tasks"][0]["remaining"] == 5
    rejected = call(desk, "submit", task="C001", patch="seventh")
    assert not rejected["ok"] and "retry reserve" in rejected["error"]
    assert rejected["progress"]["gap"] == 1
    call(desk, "next", uid=2002)
    assert call(desk, "submit", uid=2002, task="C001", patch="other account")["ok"]


def test_reprojecting_stored_summary_drops_unrecognized_fields_and_invalid_test_names():
    raw = {
        "status": "failed",
        "tests_run": 3,
        "feedback": SECRET,
        "counts": {"secret": SECRET},
        "tests": [{"name": SECRET, "status": "failed", "traceback": SECRET}],
    }
    result = server.result_summary(raw, EXPECTED)
    assert SECRET not in json.dumps(result)
    assert result["counts"]["unknown"] == 3


def test_full_assignment_retains_every_maximum_patch_and_raw_result_under_collection_cap(desk):
    # This deliberately exercises the entire normal allocation with unique maximum-size
    # artifacts, not compressed/reused patches. It never executes submitted code.
    # Also reserve the maximum 128-ID summary, all 80 infrastructure retries,
    # and every account's full report allowance. Raw controller records stay private.
    for task in desk.catalog["tasks"].values():
        task["expected_tests"] = [f"test_task.TestTask.test_case_{i:03}" for i in range(1, 129)]
    for uid in range(2001, 2005):
        for task in desk.catalog["assignments"][str(uid)]:
            assert call(desk, "next", uid=uid)["fetch_task"] == task
            if int(task[1:]) <= 4:
                for retry in range(5):
                    tag = f"{uid}/{task}/infrastructure-{retry}:"
                    patch = tag + "x" * (server.PATCH_LIMIT - len(tag))
                    receipt = call(desk, "submit", uid=uid, task=task, patch=patch)
                    assert receipt["ok"], receipt
                    response = complete(
                        desk, receipt, uid=uid, status="infrastructure_error", feedback=SECRET + "x" * 29_000
                    )
                    assert response["refunded"]
            for attempt in range(5):
                tag = f"{uid}/{task}/{attempt}:"
                patch = tag + "x" * (server.PATCH_LIMIT - len(tag))
                receipt = call(desk, "submit", uid=uid, task=task, patch=patch)
                assert receipt["ok"], receipt
                response = complete(desk, receipt, uid=uid, feedback=SECRET + "x" * 29_000)
                assert response["status"] == "failed"
                assert response["progress"]["tasks"][int(task[1:]) - 1]["remaining"] == 4 - attempt
            report = call(desk, "flag", uid=uid, task=task, note="n" * 4000)
            assert report["ok"], report
        assert call(desk, "status", uid=uid)["gap"] == 20
        for _ in range(server.REPORT_LIMIT - 20):
            assert call(desk, "flag", uid=uid, task="C020", note="n" * 4000)["ok"]
    assert desk.db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 480
    assert len(list((desk.state / "submissions").glob("*.diff"))) == 480
    assert len(list((desk.state / "jobs").glob("*.result.json"))) == 480
    assert desk._storage_used() < 58 * 1024 * 1024
    # Reserve room for the separately written broker/service logs, final ledger and
    # collector metadata; normal full-budget work must never hit the admission cap.
    (desk.state / "broker_events.jsonl").write_text("x" * 1_000_000)
    (desk.state / "output.log").write_text("x" * 1_000_000)
    desk.finalize()
    assert desk._storage_used() < server.STATE_LIMIT < 64 * 1024 * 1024
    print(f"Maximum-budget retained evidence: {desk._storage_used()} bytes including log reserves")
    for row in desk.db.execute("SELECT sha FROM submissions"):
        assert (
            hashlib.sha256((desk.state / "submissions" / (row[0] + ".diff")).read_bytes()).hexdigest()
            == row[0]
        )
