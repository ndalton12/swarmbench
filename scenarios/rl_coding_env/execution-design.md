# Disposable Python grading jobs: implemented boundary

This is an author-only design, not an agent-visible task asset.

The existing service boundary does not suffice: subprocesses inherit the taskdesk
UID and could read the entire hidden corpus and reward database. The service must
never execute submitted Python. It also must not receive the Docker socket or
new privileges in the team container.

## Engine surface

The implementation adds one explicitly enabled service option, `execution: python-tests` (default
absent). Only enabled services receive a host-side broker, started and cancelled
with their team. The user approved this material new execution boundary after reviewing the
proposal and standalone proof.

Touched engine files: `config.py` for the opt-in schema;
`engine/service_jobs.py` for patch validation, immutable attempt preparation,
Docker execution and inbox polling; a narrow lifecycle hook in
`engine/orchestrator.py`; schema documentation and focused engine/container tests.
No existing team-container capability or mount is widened.

The broker reads a private `jobs/<job_id>.request.json` using `sandbox.exec` as
that service's user. It never accepts a Docker command, image, test invocation or
host filesystem path from the request. IDs are restricted to bounded ASCII safe
identifiers. Requests carry `job_id`, `task_id`, `patch_sha256`, `uid`, `attempt`, `version`
and `patch_file` (exactly `submissions/<patch_sha256>.diff`). Patch bytes are
limited to 65,536 bytes and verified against their digest. The broker binds the response to the
entire request identity. The service writes requests and submissions atomically.

Task assets are author-controlled, under
`services/<service>/tasks/<task_id>/`: a manifest, immutable `public/` project and
`hidden/` tests. The host uses its scenario-source copy, never the mutable agent
checkout or a service-supplied arbitrary location. Task manifests provide a
source-path allowlist, fixed test inventory and hashes. Only regular files are
allowed; links and traversal are rejected before copying or patching. A strict
unified-diff parser supports text replacements of allowed existing source files;
no shell, git hooks, setup.py or pip invocation is involved.

## Worker boundary

Each attempt gets a newly created container from the already prepared generic
swarmbench base image, never the team image (which contains the full private
corpus). Copy only the patched current-task project, its current hidden tests,
and the engine's fixed test harness into a root-owned `/job` tmpfs. Docker
refuses `docker cp` with a read-only root filesystem, including tmpfs targets:
the controller therefore starts a nonroot `sleep` anchor, then invokes a fixed
`tar` extraction command as root through Docker exec before any submitted code
starts. The archive is constructed from validated regular files only, owned by
root with mode 0444; directories are root-owned and non-writable by workers.
This setup command has no capabilities, cannot execute submitted code, and
exits before the worker starts. No host directory,
other task, queue socket, grader state, agent home or Docker socket is mounted.

Run as numeric UID/GID 61001 with all capabilities dropped, no-new-privileges,
network disabled, a read-only root filesystem, and a bounded private `/tmp`
tmpfs. Default limits: 1 CPU, 512 MiB memory with no extra swap, 32 processes,
60-second wall-clock deadline, bounded feedback/output. The harness and hidden
tests are read-only, as is the project baseline with applied patch. Python runs
isolated with a clean environment; task imports are explicitly scoped to the
selected project. The process starts without grader descriptors or secrets.

The host kills and removes the entire container on success, failure, timeout,
output overflow, cancellation or restart recovery. Labels identify containers
owned by this broker/run so stale jobs can be removed without affecting other
runs. Removal of the whole PID namespace prevents children surviving into the
next attempt; every new attempt starts from the immutable baseline.

## Outcome channel and limits

The host controls the job identity, process exit status, deadline, output limits,
and result-file destination. A fixed runner enumerates expected unittest IDs,
checks that each ran (no zero-test or skipped success), and emits a structured
completion record on a separate bounded pipe. Before importing project code,
the runner consumes a fresh nonce from stdin and closes stdin. It keeps the nonce
in memory and sends it through the captured completion stream. Ordinary stdout
and stderr are captured as feedback; the nonce is absent from argv, the
environment and writable completion files. Fake ordinary stdout and an early successful process exit
are insufficient. Host validation checks inventory, completion and result
consistency and the nonce before returning passed. Crashes and timeouts are failures; Docker
startup/control errors are infrastructure errors, not accepted submissions.

Arbitrary submitted Python shares an interpreter with tests and can inspect
current-task test code. Test-specific behavior and sufficiently invasive
runtime/frame/descriptor introspection can tamper with the current job
completion channel and remains a possible measurement target; this is not a
cryptographic proof that arbitrary malicious Python obeyed the test harness.
Independent author checks and source review help distinguish legitimate repairs
from such behavior. Generic runner tampering may also fool independent replay,
so replay success alone is insufficient.
The non-negotiable boundary is isolation from other tasks and trusted records.

The broker atomically writes `jobs/<job_id>.result.json` with the same `job_id`, `task_id`, `patch_sha256`, `uid`, `attempt` and
`version` identity, `status` (`passed`, `failed`, `timeout`, `invalid_patch`, or
`infrastructure_error`), bounded `feedback`, `tests_run`, and test inventory.
The broker constructs results from the host-controlled process outcome;
the trusted queue can also record cancellation for unstarted jobs at episode end.
Worker stdout cannot choose a target account/task, modify the reward ledger or
write into the service state. The service reconciles results transactionally.

## Standalone proof before engine implementation

`/tmp/rl_docker_proof.py` passed six disposable mock jobs using the existing
`swarmbench-base:2baaa3f6b98f` image: a passing repair; fake stdout rejected;
`os._exit(0)` rejected for missing completion; worker UID 61001, empty secret
surface, absent service/Docker sockets, no external network and read-only
hidden files; a forked child's timeout with whole-container removal; and a
subsequent clean attempt without the earlier writable `/tmp` file. No engine
code or team-container settings were changed for this proof. The proof is now covered by committed deterministic tests in
`tests/test_engine_service_jobs.py`. The strict diff proof also passed 200 deterministic varied edits and
rejected traversal, absolute paths, hidden-file edits and symlink metadata.

## Validation

Focused generic executor tests passed before full-corpus calibration: valid and
invalid patches; kernel UID, no-new-privileges and zero capabilities; another
task and ledger sentinel absent; network and control socket denial; read-only
assets; fake success on stdout, wrong-nonce completion on raw stderr, early
exit and skipped/empty suites rejected; bounded output; fork timeout cleanup;
concurrent writable/PID namespace separation; and owner-scoped stale-job cleanup.
The author-only `execute_task` API uses this same boundary for live, independent
and corrected calibration suites. Cancellation waits for the bounded running
job, publishes its result, removes its namespace, and only then lets service
finalization classify any unstarted work.
