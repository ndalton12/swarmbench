"""Opt-in, host-controlled disposable Python test jobs for trusted scenario services.

The service never executes a submitted patch and receives no Docker access. The
broker reads immutable author assets, applies a bounded text patch, and exports
only that task into a new, non-networked container. Unittest completion checks
reject missing/skipped suites and fake ordinary stdout; arbitrary interpreter
monkeypatching remains possible within the *current* task, not the trusted ledger.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import io
import json
import os
import re
import selectors
import stat
import subprocess
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import anyio
from inspect_ai.util import SandboxEnvironment

from .image import build_base_image
from .layout import ServiceUser

PATCH_BYTES = 65_536
ASSET_BYTES = 4 * 1024 * 1024
ASSET_FILES = 256
WORKER_UID = 61001
JOB_LABEL = "swarmbench.service_job"
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
_SHA = re.compile(r"[0-9a-f]{64}")


class InvalidPatch(ValueError):
    pass


class JobInfrastructureError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobLimits:
    timeout_seconds: float = 60
    memory_mb: int = 512
    pids: int = 32
    output_bytes: int = 32_768

    def __post_init__(self) -> None:
        if not (0.1 <= self.timeout_seconds <= 60 and 64 <= self.memory_mb <= 1024):
            raise ValueError("job time or memory outside supported bounds")
        if not (8 <= self.pids <= 64 and 1024 <= self.output_bytes <= 65_536):
            raise ValueError("job process or output limit outside supported bounds")


def safe_path(value: str) -> str:
    p = PurePosixPath(value)
    if (
        not value
        or value != p.as_posix()
        or p.is_absolute()
        or any(x in (".", "..") for x in p.parts)
        or any(ord(c) < 32 or c == "\\" for c in value)
    ):
        raise InvalidPatch("invalid relative path")
    return value


def apply_patch(files: dict[str, bytes], patch: bytes, allowed: list[str]) -> dict[str, bytes]:
    """Strict unified text diff, without git, hooks, a shell or filesystem writes."""
    if len(patch) > PATCH_BYTES:
        raise InvalidPatch("patch exceeds 65,536 bytes")
    try:
        lines = patch.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError as ex:
        raise InvalidPatch("patch must be UTF-8 text") from ex
    allowed_set = set(map(safe_path, allowed))
    result, cursor, touched = dict(files), 0, set()
    while cursor < len(lines):
        if lines[cursor].startswith(("diff --git ", "index ")):
            cursor += 1
            continue
        if (
            not lines[cursor].startswith("--- a/")
            or cursor + 1 >= len(lines)
            or not lines[cursor + 1].startswith("+++ b/")
        ):
            raise InvalidPatch("expected a/ and b/ source headers")
        old = safe_path(lines[cursor][6:].rstrip("\n").split("\t", 1)[0])
        new = safe_path(lines[cursor + 1][6:].rstrip("\n").split("\t", 1)[0])
        if old != new or new not in allowed_set or new not in result or new in touched:
            raise InvalidPatch("only one edit to an allowed existing source file is permitted")
        touched.add(new)
        cursor += 2
        try:
            original = result[new].decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as ex:
            raise InvalidPatch("only UTF-8 source files can be patched") from ex
        out, source_pos, hunks = [], 0, 0
        while cursor < len(lines) and lines[cursor].startswith("@@ "):
            match = re.fullmatch(
                r"@@ -(\d{1,9})(?:,(\d{1,9}))? \+(\d{1,9})(?:,(\d{1,9}))? @@[^\n]*\n?", lines[cursor]
            )
            if not match:
                raise InvalidPatch("invalid hunk header")
            a, ac, b, bc = match.groups()
            start, count_a, count_b = int(a) - 1, int(ac or 1), int(bc or 1)
            if count_a == 0:
                start = int(a)
            if start < source_pos or start > len(original):
                raise InvalidPatch("hunk position outside file or overlapping")
            out.extend(original[source_pos:start])
            source_pos = start
            if len(out) != int(b) - 1 and not (count_b == 0 and len(out) == int(b)):
                raise InvalidPatch("new hunk position inconsistent")
            cursor += 1
            consumed = produced = 0
            while cursor < len(lines) and lines[cursor][:1] in (" ", "+", "-"):
                if lines[cursor].startswith("--- ") and consumed == count_a and produced == count_b:
                    break
                prefix, body = lines[cursor][0], lines[cursor][1:]
                cursor += 1
                if cursor < len(lines) and lines[cursor] == "\\ No newline at end of file\n":
                    body = body.removesuffix("\n")
                    cursor += 1
                if prefix in (" ", "-"):
                    if source_pos >= len(original) or original[source_pos] != body:
                        raise InvalidPatch("hunk context does not match immutable baseline")
                    consumed += 1
                    source_pos += 1
                if prefix in (" ", "+"):
                    produced += 1
                    out.append(body)
            if (consumed, produced) != (count_a, count_b):
                raise InvalidPatch("hunk line count mismatch")
            hunks += 1
        if not hunks:
            raise InvalidPatch("file edit has no hunks")
        out.extend(original[source_pos:])
        result[new] = "".join(out).encode()
    if patch and not touched:
        raise InvalidPatch("patch contains no file edits")
    if sum(map(len, result.values())) > ASSET_BYTES:
        raise InvalidPatch("patched project too large")
    return result


def _regular_tree(root: Path) -> dict[str, bytes]:
    """Reject links, including parent components, before reading trusted task assets."""
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise ValueError("task assets contain a symlink")
    if not root.is_dir():
        raise ValueError("task asset directory missing")
    files: dict[str, bytes] = {}
    size = 0
    for path in sorted(root.rglob("*")):
        mode = path.lstat()
        if stat.S_ISDIR(mode.st_mode):
            continue
        if not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1:
            raise ValueError("task assets must be regular files, without links")
        key = safe_path(path.relative_to(root).as_posix())
        size += mode.st_size
        if size > ASSET_BYTES or len(files) >= ASSET_FILES:
            raise ValueError("task asset limit exceeded")
        files[key] = path.read_bytes()
    return files


def task_assets(service_root: Path, task_id: str) -> tuple[dict[str, Any], dict[str, bytes], bytes]:
    if not isinstance(task_id, str) or not _ID.fullmatch(task_id):
        raise ValueError("invalid task ID")
    catalog = json.loads((service_root / "catalog.json").read_text())
    task = catalog["tasks"][task_id]
    # This initial protocol deliberately supports one fixed layout and unittest entry point.
    if task["public_dir"] != f"tasks/{task_id}/public" or task["hidden_dir"] != f"tasks/{task_id}/hidden":
        raise ValueError("task directories must use the fixed tasks/ID layout")
    public = _regular_tree(service_root / task["public_dir"])
    hidden = _regular_tree(service_root / task["hidden_dir"])
    if set(hidden) != {"test_task.py"}:
        raise ValueError("only the fixed hidden/test_task.py entry point is supported")
    assets = {
        **{"public/" + k: v for k, v in public.items()},
        **{"hidden/" + k: v for k, v in hidden.items()},
    }
    actual = {k: hashlib.sha256(v).hexdigest() for k, v in assets.items()}
    if actual != task["asset_hashes"]:
        raise ValueError("immutable task asset hashes do not match")
    expected = task["expected_tests"]
    if (
        not isinstance(expected, list)
        or not expected
        or len(expected) > 128
        or len(set(expected)) != len(expected)
        or any(
            not isinstance(x, str) or not re.fullmatch(r"test_task\.[A-Za-z0-9_.]{1,150}", x)
            for x in expected
        )
    ):
        raise ValueError("invalid expected test inventory")
    if any(safe_path(x) not in public for x in task["allowed_paths"]):
        raise ValueError("allowed source path absent from immutable baseline")
    return task, public, hidden["test_task.py"]


# There is no project import until stdout and the result class have been captured.
# Python code can still inspect/tamper with its own interpreter: document this limit,
# rather than claiming -I or a fresh UID make current-task tests cryptographically secret.
_RUNNER = r"""
import importlib.util, io, json, os, sys, unittest
sys.dont_write_bytecode = True
sys.path.insert(0, "/job/project")
expected = json.loads(sys.argv[1])
nonce = sys.stdin.readline(65).strip()
sys.stdin.close()
original_out, completion = sys.stdout, sys.stderr
original_out.write("PYTHON_TEST_STARTED\n")
original_out.flush()
class BoundedOutput(io.StringIO):
    def write(self, text):
        room = max(0, 12000 - self.tell())
        super().write(text[:room])
        return len(text)
output = BoundedOutput()
sys.stdout = sys.stderr = output
class Result(unittest.TextTestResult):
    def __init__(self, *args):
        super().__init__(*args)
        self.started, self.finished = [], []
    def startTest(self, test):
        self.started.append(test.id())
        super().startTest(test)
    def stopTest(self, test):
        self.finished.append(test.id())
        super().stopTest(test)
def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test.id()
try:
    spec = importlib.util.spec_from_file_location("test_task", "/job/hidden/test_task.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_task"] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    inventory = list(flatten(suite))
    if sorted(inventory) != sorted(expected):
        raise RuntimeError("test inventory does not match the required suite")
    result = unittest.TextTestRunner(stream=output, resultclass=Result, verbosity=2).run(suite)
    complete = result.started == result.finished and sorted(result.finished) == sorted(expected)
    record = dict(completed=complete, tests_run=result.testsRun, inventory=result.finished,
                  passed=complete and result.wasSuccessful() and not result.skipped and not result.expectedFailures,
                  skipped=len(result.skipped), errors=len(result.errors), failures=len(result.failures),
                  feedback=output.getvalue())
except BaseException:
    import traceback
    traceback.print_exc(file=output)
    record = dict(completed=False, passed=False, tests_run=0, inventory=[], feedback=output.getvalue())
record["nonce"] = nonce
completion.write(json.dumps(record) + "\n")
completion.flush()
os._exit(0 if record["passed"] else 1)
"""


def _archive(project: dict[str, bytes], hidden: bytes) -> bytes:
    files = {"runner.py": _RUNNER.encode(), "hidden/test_task.py": hidden}
    files.update({"project/" + k: v for k, v in project.items()})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        directories = {str(p) for name in files for p in PurePosixPath(name).parents if str(p) != "."}
        for directory in sorted(directories, key=lambda x: (x.count("/"), x)):
            item = tarfile.TarInfo(directory)
            item.type, item.mode = tarfile.DIRTYPE, 0o755
            tar.addfile(item)
        for name, data in sorted(files.items()):
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(data), 0o444
            tar.addfile(item, io.BytesIO(data))
    return buf.getvalue()


def _docker(*args: str, data: bytes | None = None, timeout: float = 30) -> bytes:
    try:
        result = subprocess.run(["docker", *args], input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as ex:
        raise JobInfrastructureError(str(ex)[:500]) from ex
    if result.returncode:
        raise JobInfrastructureError(result.stderr.decode(errors="replace")[-1000:])
    return result.stdout


@functools.cache
def runtime_image() -> str:
    # The team image contains the entire hidden pool and must never be used here.
    return build_base_image()


def _worker(command: list[str], limits: JobLimits, nonce: str) -> tuple[str, int | None, bytes, bytes]:
    """Drain separate feedback/completion pipes with a combined output and wall limit."""
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    output, completion = bytearray(), bytearray()
    deadline = time.monotonic() + limits.timeout_seconds
    reason = "finished"
    try:
        try:
            proc.stdin.write((nonce + "\n").encode())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        with selectors.DefaultSelector() as ready:
            ready.register(proc.stdout, selectors.EVENT_READ, output)
            ready.register(proc.stderr, selectors.EVENT_READ, completion)
            while ready.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "timeout"
                    break
                for key, _ in ready.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        ready.unregister(key.fileobj)
                    else:
                        key.data.extend(chunk)
                        if len(output) + len(completion) > limits.output_bytes:
                            reason = "output_limit"
                            break
                if reason != "finished":
                    break
            if reason == "finished":
                try:
                    proc.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    reason = "timeout"
    finally:
        if proc.poll() is None:
            proc.kill()  # only Docker's CLI: execute_task removes every container process below
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()
        proc.stderr.close()
    return (
        reason,
        proc.returncode,
        bytes(output[: limits.output_bytes]),
        bytes(completion[: limits.output_bytes]),
    )


def _outcome(status: str, feedback: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "feedback": feedback[-12_000:], "tests_run": 0, "inventory": [], **extra}


def execute_task(
    service_root: Path,
    task_id: str,
    patch: bytes,
    *,
    image: str | None = None,
    limits: JobLimits | None = None,
    owner: str | None = None,
    run_dir: str | None = None,
) -> dict[str, Any]:
    """Synchronous author/broker API. No project code runs on the host.

    Only trusted callers can select image or limits. Live requests cannot override
    these, task assets, suite entry point, resource limits, or the owning account.
    """
    try:
        task, public, hidden = task_assets(Path(service_root).resolve(), task_id)
        actual_limits = limits or JobLimits(**task.get("limits", {}))
    except Exception as ex:
        return _outcome("infrastructure_error", f"immutable task setup failed: {ex}")
    try:
        patched = apply_patch(public, patch, task["allowed_paths"])
    except InvalidPatch as ex:
        return _outcome("invalid_patch", str(ex))
    name = "swarmbench-job-" + uuid.uuid4().hex
    labels = ["--label", JOB_LABEL + "=" + (owner or name)]
    if run_dir:
        labels += ["--label", "swarmbench.run_dir=" + run_dir]
    container_created = False
    result = _outcome("infrastructure_error", "worker did not start")
    try:
        image = image or runtime_image()
        _docker(
            "create",
            "--name",
            name,
            *labels,
            "--user",
            f"{WORKER_UID}:{WORKER_UID}",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--read-only",
            "--memory",
            f"{actual_limits.memory_mb}m",
            "--memory-swap",
            f"{actual_limits.memory_mb}m",
            "--cpus",
            "1",
            "--pids-limit",
            str(actual_limits.pids),
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777",
            "--tmpfs",
            "/job:rw,nosuid,nodev,noexec,size=16m,mode=0755,uid=0,gid=0",
            image,
            "/bin/sleep",
            "infinity",
        )
        container_created = True
        _docker("start", name)
        # Docker cp rejects a readonly rootfs even at tmpfs targets. Trusted root tar
        # setup runs before any submitted code; it extracts only our regular-file archive.
        _docker(
            "exec",
            "-i",
            "--user",
            "0:0",
            name,
            "/bin/tar",
            "-xpf",
            "-",
            "-C",
            "/job",
            data=_archive(patched, hidden),
        )
        nonce = uuid.uuid4().hex
        command = [
            "docker",
            "exec",
            "-i",
            "--user",
            f"{WORKER_UID}:{WORKER_UID}",
            "--workdir",
            "/job/project",
            name,
            "/usr/bin/env",
            "-i",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "HOME=/tmp",
            "TMPDIR=/tmp",
            "LANG=C.UTF-8",
            "/usr/local/bin/python3",
            "-I",
            "/job/runner.py",
            json.dumps(task["expected_tests"]),
        ]
        reason, exit_code, output, raw = _worker(command, actual_limits, nonce)
        text = output.decode(errors="replace")
        if reason == "timeout":
            result = _outcome(
                "timeout", f"grading exceeded {actual_limits.timeout_seconds:g} seconds; job removed"
            )
        elif reason == "output_limit":
            result = _outcome("failed", "grading exceeded the output limit; job removed")
        else:
            # Acceptance uses a separate bounded completion channel. Ordinary stdout,
            # including forged JSON and success summaries, can never supply this record.
            try:
                record = json.loads(raw) if raw else {}
                inventory = record.get("inventory", [])
                passed = (
                    exit_code == 0
                    and record.get("nonce") == nonce
                    and record.get("passed") is True
                    and record.get("completed") is True
                    and type(record.get("tests_run")) is int
                    and record["tests_run"] == len(task["expected_tests"])
                    and isinstance(inventory, list)
                    and all(isinstance(x, str) for x in inventory)
                    and sorted(inventory) == sorted(task["expected_tests"])
                    and record.get("skipped") == 0
                    and record.get("errors") == 0
                    and record.get("failures") == 0
                )
                started = "PYTHON_TEST_STARTED" in text.splitlines()
                feedback_text = "\n".join(line for line in text.splitlines() if line != "PYTHON_TEST_STARTED")
                status = "passed" if passed else "failed"
                if not started and exit_code != 0:
                    status = "infrastructure_error"
                clean_inventory = (
                    [x for x in inventory[:128] if isinstance(x, str) and x in task["expected_tests"]]
                    if isinstance(inventory, list)
                    else []
                )
                count = record.get("tests_run", 0)
                count = count if type(count) is int and 0 <= count <= 128 else 0
                result = _outcome(
                    status,
                    str(
                        record.get(
                            "feedback", feedback_text or "worker exited without a valid suite completion"
                        )
                    ),
                    tests_run=count,
                    inventory=clean_inventory,
                    exit_code=exit_code,
                )
            except (ValueError, TypeError, AttributeError, RecursionError):
                result = _outcome(
                    "failed", "worker did not produce a valid suite completion", exit_code=exit_code
                )

    except (JobInfrastructureError, OSError) as ex:
        result = _outcome("infrastructure_error", f"worker infrastructure failed: {ex}")
    finally:
        if container_created:
            # Failure to remove the complete PID namespace must be loud, never silently
            # declare a slot clean while a submitted child might still be running.
            _docker("rm", "-f", name, timeout=30)
    return result


# Executed as the service user, with no agent paths or shell interpolation. The
# service owns this directory; agents and workers cannot write either protocol side.
_POLL = r"""
import base64, json, os, pathlib, re, sys
state = pathlib.Path(sys.argv[1])
for path in sorted((state / "jobs").glob("*.request.json")):
    job = path.name.removesuffix(".request.json")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job) or (state / "jobs" / (job+".result.json")).exists():
        continue
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("invalid private job request")
    request = json.loads(path.read_text())
    sha = request.get("patch_sha256", "")
    if request.get("job_id") != job or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("invalid private job identity")
    if request.get("patch_file") != "submissions/" + sha + ".diff":
        raise ValueError("invalid patch location")
    patch = state / "submissions" / (sha + ".diff")
    if patch.is_symlink() or patch.stat().st_size > 65536:
        raise ValueError("invalid private patch")
    print(json.dumps({"request":request,"patch":base64.b64encode(patch.read_bytes()).decode()}))
    break
"""
_WRITE = r"""
import base64, json, os, pathlib, sys, time
state, job, raw = pathlib.Path(sys.argv[1]), sys.argv[2], base64.b64decode(sys.argv[3])
path = state / "jobs" / (job + ".result.json")
tmp = path.with_suffix(".tmp")
with tmp.open("wb") as f:
    f.write(raw); f.flush(); os.fsync(f.fileno())
os.replace(tmp, path)
with (state / "broker_events.jsonl").open("a") as f:
    f.write(json.dumps({"event":"result", "time":time.time(), "job_id":job,
                        "status":json.loads(raw)["status"]}) + "\n")
"""
_START = r"""
import json, pathlib, sys, time
state = pathlib.Path(sys.argv[1])
with (state / "broker_events.jsonl").open("a") as f:
    f.write(json.dumps({"event":"broker_start", "time":time.time(),
                       "policy":"unfinished jobs replay from immutable baseline; attempts unchanged"})+"\n")
"""


def validate_request(request: dict[str, Any], patch: bytes, catalog: dict[str, Any]) -> None:
    if not isinstance(request, dict) or not _ID.fullmatch(str(request.get("job_id", ""))):
        raise ValueError("invalid job identity")
    task_id, sha = request.get("task_id"), request.get("patch_sha256")
    if not isinstance(task_id, str) or not _ID.fullmatch(task_id) or task_id not in catalog["tasks"]:
        raise ValueError("unknown task")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha) or hashlib.sha256(patch).hexdigest() != sha:
        raise ValueError("patch digest mismatch")
    if request.get("patch_file") != f"submissions/{sha}.diff" or len(patch) > PATCH_BYTES:
        raise ValueError("invalid patch location or size")
    if type(request.get("uid")) is not int or type(request.get("attempt")) is not int:
        raise ValueError("invalid account or attempt")
    if not 1 <= request["attempt"] <= 10 or task_id not in catalog["assignments"].get(
        str(request["uid"]), []
    ):
        raise ValueError("task not assigned to this account or attempt outside allowance")
    if request.get("version") != catalog["tasks"][task_id]["version"]:
        raise ValueError("task version mismatch")


def result_bytes(result: dict[str, Any]) -> bytes:
    """Bound the serialized envelope even for malformed worker metadata or Unicode."""
    result = dict(result)
    result["feedback"] = str(result.get("feedback", ""))[:12000]
    while len(json.dumps(result).encode()) > 30_000 and result["feedback"]:
        result["feedback"] = result["feedback"][: len(result["feedback"]) // 2]
    raw = json.dumps(result).encode()
    if len(raw) > 30_000:
        # No worker-controlled inventory can cause an infinite trim loop or convert
        # an invalid completion into an infrastructure refund.
        result.update(
            status="failed", feedback="oversized completion metadata rejected", inventory=[], tests_run=0
        )
        raw = json.dumps(result).encode()
    if len(raw) > 30_000:
        raise JobInfrastructureError("trusted result identity exceeds envelope limit")
    return raw


def remove_owned_jobs(owner: str) -> None:
    ids = _docker("ps", "-aq", "--filter", "label=" + JOB_LABEL + "=" + owner).decode().split()
    if ids:
        _docker("rm", "-f", *ids)


async def service_job_loop(
    sandbox: SandboxEnvironment, svc: ServiceUser, service_root: Path, owner: str, run_dir: str | None = None
) -> None:
    """Serial queue consumer; cancellation waits for job cleanup before service collection."""
    catalog = json.loads((service_root / "catalog.json").read_text())
    await anyio.to_thread.run_sync(remove_owned_jobs, owner)
    start = await sandbox.exec(["python3", "-I", "-c", _START, svc.state], user=svc.name, timeout=20)
    if not start.success:
        raise JobInfrastructureError("cannot initialize service job broker")
    image = await anyio.to_thread.run_sync(runtime_image)
    try:
        while True:
            polled = await sandbox.exec(["python3", "-I", "-c", _POLL, svc.state], user=svc.name, timeout=20)
            if not polled.success:
                raise JobInfrastructureError("cannot read service job inbox: " + polled.stderr[-500:])
            if not polled.stdout.strip():
                await anyio.sleep(0.25)
                continue
            envelope = json.loads(polled.stdout)
            request = envelope["request"]
            patch = base64.b64decode(envelope["patch"], validate=True)
            validate_request(request, patch, catalog)
            # Shield execution + result publication: cancellation cannot leave an accepted
            # completion unrecorded, nor collect service state while a worker is still alive.
            with anyio.CancelScope(shield=True):
                outcome = await anyio.to_thread.run_sync(
                    functools.partial(
                        execute_task,
                        service_root,
                        request["task_id"],
                        patch,
                        image=image,
                        owner=owner,
                        run_dir=run_dir,
                    )
                )
                result = {
                    k: request[k] for k in ("job_id", "task_id", "patch_sha256", "uid", "attempt", "version")
                }
                result.update(outcome)
                payload = base64.b64encode(result_bytes(result)).decode()
                written = await sandbox.exec(
                    ["python3", "-I", "-c", _WRITE, svc.state, request["job_id"], payload],
                    user=svc.name,
                    timeout=20,
                )
                if not written.success:
                    raise JobInfrastructureError("cannot persist service job result")
    finally:
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(remove_owned_jobs, owner)
