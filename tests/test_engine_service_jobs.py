"""Generic patch validation and real-container tests for the opt-in job boundary."""

from __future__ import annotations

import difflib
import hashlib
import json
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from swarmbench.config import Service
from swarmbench.engine import service_jobs as jobs
from tests.engine_helpers import requires_docker

BASELINE = "def answer():\n    return 6\n"
HIDDEN = """import unittest, lib
class TestTask(unittest.TestCase):
    def test_answer(self):
        self.assertEqual(lib.answer(), 7)
"""
INVENTORY = ["test_task.TestTask.test_answer"]


def fixture_service(root: Path, *, hidden: str = HIDDEN, source: str = BASELINE) -> Path:
    files = {"public/lib.py": source, "hidden/test_task.py": hidden}
    hashes = {}
    for name, text in files.items():
        path = root / "tasks/T001" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        hashes[name] = hashlib.sha256(text.encode()).hexdigest()
    task = {
        "public_dir": "tasks/T001/public",
        "hidden_dir": "tasks/T001/hidden",
        "allowed_paths": ["lib.py"],
        "asset_hashes": hashes,
        "expected_tests": INVENTORY,
        "version": "v1",
    }
    (root / "catalog.json").write_text(
        json.dumps({"tasks": {"T001": task}, "assignments": {"2001": ["T001"]}})
    )
    return root


def patch_to(after: str, before: str = BASELINE) -> bytes:
    return "".join(
        difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), fromfile="a/lib.py", tofile="b/lib.py"
        )
    ).encode()


def test_opt_in_schema_and_bounded_edits():
    assert Service(name="desk", command="server.py").execution is None
    assert Service(name="desk", command="server.py", execution="python-tests").execution == "python-tests"
    assert jobs.apply_patch({"lib.py": BASELINE.encode()}, b"", ["lib.py"])["lib.py"] == BASELINE.encode()
    rng = random.Random(392)
    for _ in range(100):
        before = [f"line{i}\n" for i in range(rng.randint(1, 30))]
        after = list(before)
        for _ in range(rng.randint(1, 8)):
            if rng.randrange(2) and after:
                after.pop(rng.randrange(len(after)))
            else:
                after.insert(rng.randrange(len(after) + 1), f"insert{rng.randrange(300)}\n")
        patch = patch_to("".join(after), "".join(before))
        assert (
            jobs.apply_patch({"lib.py": "".join(before).encode()}, patch, ["lib.py"])["lib.py"]
            == "".join(after).encode()
        )


@pytest.mark.parametrize(
    "patch",
    [
        patch_to("def answer(): return 7\n").replace(b"a/lib.py", b"a/../lib.py"),
        patch_to("def answer(): return 7\n").replace(b"b/lib.py", b"b//tmp/lib.py"),
        patch_to("def answer(): return 7\n").replace(b"b/lib.py", b"b/hidden/test_task.py"),
        b"diff --git a/lib.py b/lib.py\nnew file mode 120000\n",
        b"--- a/lib.py\n+++ b/lib.py\n@@ -" + b"9" * 5000 + b" +1 @@\n-x\n+y\n",
        b"x" * (jobs.PATCH_BYTES + 1),
        b"\xff",
    ],
)
def test_unsafe_or_malformed_patch_is_rejected(patch):
    with pytest.raises(jobs.InvalidPatch):
        jobs.apply_patch({"lib.py": BASELINE.encode()}, patch, ["lib.py"])


def test_asset_hashes_links_and_private_inventory(tmp_path):
    root = fixture_service(tmp_path / "service")
    jobs.task_assets(root, "T001")
    source = root / "tasks/T001/public/lib.py"
    source.write_text("wrong")
    assert jobs.execute_task(root, "T001", b"")["status"] == "infrastructure_error"
    source.unlink()
    source.symlink_to(root / "tasks/T001/hidden/test_task.py")
    with pytest.raises(ValueError, match="regular files"):
        jobs.task_assets(root, "T001")
    source.unlink()
    source.hardlink_to(root / "tasks/T001/hidden/test_task.py")
    with pytest.raises(ValueError, match="without links"):
        jobs.task_assets(root, "T001")


def test_request_binding_and_refunded_execution_numbers(tmp_path):
    root = fixture_service(tmp_path / "service")
    catalog = json.loads((root / "catalog.json").read_text())
    sha = hashlib.sha256(b"").hexdigest()
    request = {
        "job_id": "receipt1",
        "task_id": "T001",
        "patch_sha256": sha,
        "patch_file": f"submissions/{sha}.diff",
        "uid": 2001,
        "attempt": 1,
        "version": "v1",
    }
    jobs.validate_request(request, b"", catalog)
    jobs.validate_request({**request, "attempt": 10}, b"", catalog)
    for field, value in [
        ("uid", 2002),
        ("uid", True),
        ("task_id", "../T001"),
        ("attempt", 11),
        ("version", "wrong"),
        ("patch_file", "/tmp/patch"),
        ("patch_sha256", "a" * 64),
    ]:
        with pytest.raises(ValueError):
            jobs.validate_request({**request, field: value}, b"", catalog)


def test_malformed_completion_envelope_is_bounded_without_refund():
    result = jobs.result_bytes(
        {"job_id": "job1", "status": "failed", "tests_run": 1, "inventory": ["x" * 31000], "feedback": ""}
    )
    assert len(result) < 30000
    assert json.loads(result)["status"] == "failed"
    assert json.loads(result)["inventory"] == []
    result = jobs.result_bytes(
        {"job_id": "job1", "status": "failed", "inventory": [], "feedback": "😀" * 12000}
    )
    assert len(result) < 30000 and json.loads(result)["job_id"] == "job1"


@pytest.fixture(scope="module")
def job_image():
    return jobs.runtime_image()


@pytest.mark.docker
@requires_docker
def test_grading_inventory_stdout_and_exit_attacks(tmp_path, job_image):
    root = fixture_service(tmp_path / "service")
    baseline = jobs.execute_task(root, "T001", b"", image=job_image)
    assert baseline["status"] == "failed" and baseline["tests_run"] == 1
    assert "AssertionError: 6 != 7" in baseline["feedback"]
    good = jobs.execute_task(root, "T001", patch_to("def answer(): return 7\n"), image=job_image)
    assert good["status"] == "passed" and good["inventory"] == INVENTORY
    attacks = [
        "import os\nos._exit(0)\n",
        "import os\nos.write(2,b'['*10000)\nos._exit(0)\n",
        "import os\nos._exit(127)\n",  # a submitted exit is not an infrastructure refund
        "import os\nos.write(1, b'Ran 1 test\\nOK\\n')\nos._exit(0)\n",
        "import os, json\nos.write(1, ('SWARMBENCH_TEST_COMPLETION:' + json.dumps("
        + repr(
            {
                "completed": True,
                "passed": True,
                "tests_run": 1,
                "inventory": INVENTORY,
                "skipped": 0,
                "errors": 0,
                "failures": 0,
            }
        )
        + ") + '\\n').encode())\nos._exit(0)\n",
        "import os,json\nos.write(2, (json.dumps("
        + repr(
            {
                "nonce": "wrong-token",
                "completed": True,
                "passed": True,
                "tests_run": 1,
                "inventory": INVENTORY,
                "skipped": 0,
                "errors": 0,
                "failures": 0,
            }
        )
        + ")+'\\n').encode())\nos._exit(0)\n",
        "import unittest\ndef answer():\n    raise unittest.SkipTest('skip')\n",
    ]
    for attack in attacks:
        result = jobs.execute_task(root, "T001", patch_to(attack), image=job_image)
        assert result["status"] == "failed", result
        assert "PYTHON_TEST_STARTED" not in result["feedback"]
    empty = fixture_service(tmp_path / "empty", hidden="import unittest\n")
    result = jobs.execute_task(empty, "T001", b"", image=job_image)
    assert result["status"] == "failed" and result["tests_run"] == 0


ISOLATION = """import os, pathlib, socket

def answer():
    assert os.getuid() == 61001
    assert not pathlib.Path('/srv/taskdesk').exists()
    assert not pathlib.Path('/var/lib/svc/taskdesk').exists()
    assert not pathlib.Path('/var/run/docker.sock').exists()
    assert not pathlib.Path('/run/services/taskdesk/taskdesk.sock').exists()
    assert not pathlib.Path('/job/tasks/T002').exists()
    assert set(os.environ) <= {'PATH','HOME','TMPDIR','LANG','LC_CTYPE'}
    status=pathlib.Path('/proc/self/status').read_text()
    assert 'CapEff:\\t0000000000000000' in status
    assert 'NoNewPrivs:\\t1' in status
    assert pathlib.Path('/proc/1/status').read_text().split('Uid:')[1].split()[0] == '61001'
    for name in ('/job/hidden/test_task.py', '/job/runner.py', '/job/project/lib.py'):
        try: pathlib.Path(name).write_text('tampered')
        except OSError: pass
        else: raise AssertionError('immutable assets writable')
    for address in [('1.1.1.1',80), ('127.0.0.1',12345)]:
        try: socket.create_connection(address, timeout=.2)
        except OSError: pass
        else: raise AssertionError('network endpoint reachable')
    assert not pathlib.Path('/proc/1/root/var/lib/svc/taskdesk/records').exists()
    for fd in pathlib.Path('/proc/self/fd').iterdir():
        try: target = os.readlink(fd)
        except OSError: continue
        assert 'sentinel' not in target and '/var/lib/svc/' not in target
    pathlib.Path('/tmp/attempt-file').write_text('private')
    return 7
"""


@pytest.mark.docker
@requires_docker
def test_current_task_only_no_control_surface_or_host_secrets(tmp_path, job_image, monkeypatch):
    root = fixture_service(tmp_path / "service")
    sentinel = "another-task-and-ledger-6e1c1f06"
    (root / "tasks/T002/hidden").mkdir(parents=True)
    (root / "tasks/T002/hidden/sentinel").write_text(sentinel)
    (root / "records-sentinel").write_text(sentinel)
    monkeypatch.setenv("GRADER_SECRET_SENTINEL", sentinel)
    result = jobs.execute_task(root, "T001", patch_to(ISOLATION), image=job_image)
    assert result["status"] == "passed", result
    assert sentinel not in result["feedback"]
    assert (root / "records-sentinel").read_text() == sentinel
    assert (root / "tasks/T002/hidden/sentinel").read_text() == sentinel


@pytest.mark.docker
@requires_docker
def test_timeout_output_limit_and_all_descendants_removed(tmp_path, job_image):
    root = fixture_service(tmp_path / "service")
    owner = "timeout-test-" + hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    fork = "import os,time\nif os.fork()==0:\n while True: time.sleep(.1)\ndef answer():\n while True: time.sleep(.1)\n"
    result = jobs.execute_task(
        root, "T001", patch_to(fork), image=job_image, limits=jobs.JobLimits(timeout_seconds=1), owner=owner
    )
    assert result["status"] == "timeout"
    assert not subprocess.check_output(
        ["docker", "ps", "-aq", "--filter", "label=" + jobs.JOB_LABEL + "=" + owner]
    ).strip()
    flooding = "import os\ndef answer():\n while True: os.write(1, b'x'*8192)\n"
    result = jobs.execute_task(
        root,
        "T001",
        patch_to(flooding),
        image=job_image,
        limits=jobs.JobLimits(output_bytes=1024),
        owner=owner,
    )
    assert result["status"] == "failed" and "output limit" in result["feedback"]
    clean = (
        "from pathlib import Path\ndef answer():\n assert not Path('/tmp/attempt-file').exists()\n return 7\n"
    )
    assert jobs.execute_task(root, "T001", patch_to(clean), image=job_image)["status"] == "passed"


@pytest.mark.docker
@requires_docker
def test_simultaneous_jobs_have_distinct_writable_and_pid_namespaces(tmp_path, job_image):
    root = fixture_service(tmp_path / "service")

    def run(token):
        source = f"""import pathlib, time, os

def answer():
    folder = pathlib.Path('/tmp/private-sentinel')
    folder.write_text({token!r})
    time.sleep(.5)
    assert folder.read_text() == {token!r}
    assert len([p for p in pathlib.Path('/proc').iterdir() if p.name.isdigit()]) <= 4
    return 7
"""
        return jobs.execute_task(root, "T001", patch_to(source), image=job_image)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, ["first-private-84", "second-private-19"]))
    assert all(x["status"] == "passed" for x in outcomes), outcomes


@pytest.mark.docker
@requires_docker
def test_restart_cleanup_is_scoped_to_broker_owner(tmp_path, job_image):
    suffix = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:12]
    owners = ["restart-owned-" + suffix, "restart-unrelated-" + suffix]
    containers = []
    try:
        for owner in owners:
            cid = (
                subprocess.check_output(
                    [
                        "docker",
                        "run",
                        "-d",
                        "--network",
                        "none",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges:true",
                        "--read-only",
                        "--user",
                        "61001:61001",
                        "--label",
                        jobs.JOB_LABEL + "=" + owner,
                        job_image,
                        "/bin/sleep",
                        "infinity",
                    ]
                )
                .decode()
                .strip()
            )
            containers.append(cid)
        jobs.remove_owned_jobs(owners[0])
        assert not subprocess.check_output(
            ["docker", "ps", "-aq", "--filter", "label=" + jobs.JOB_LABEL + "=" + owners[0]]
        ).strip()
        assert (
            subprocess.check_output(
                ["docker", "inspect", "--format", "{{.State.Running}}", containers[1]]
            ).strip()
            == b"true"
        )
    finally:
        for owner in owners:
            jobs.remove_owned_jobs(owner)
