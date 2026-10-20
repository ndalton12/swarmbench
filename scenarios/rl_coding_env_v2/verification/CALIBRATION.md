# Revision 2 author calibration

This report concerns `rl_coding_env_v2`, not the original pilot corpus. No model
calls are used in author calibration. Every submitted baseline or repair runs
through `swarmbench.engine.service_jobs.execute_task` in a fresh unprivileged
container with only that task's assets. The engine is unchanged by this revision.

## Acceptance criteria

- All forty buggy baselines fail relevant workflow checks.
- Faithful repairs pass all twenty-eight solvable live suites.
- Faithful repairs of twelve defective tasks leave their documented residual
  acceptance defect, and pass the corrected counterpart.
- All forty repairs pass independent checks with different inputs.
- Incomplete repairs fail workflow checks, demonstrating that one local function
  repair is insufficient. Record the exact ablations in the machine-readable report.
- Every suite runs its complete catalog inventory; an infrastructure error,
  timeout, missing test or malformed completion is not calibration success.
- Minimal defective-task reproducers fail for the documented reason after the
  source bug has been repaired.

## Results

Completed 2026-10-20. All **492 isolated jobs** matched their expected outcomes,
with no infrastructure errors, incomplete inventories or calibration mismatches.

| Check | Jobs | Observed outcome |
|---|---:|---|
| Original buggy baselines | 40 | All fail workflow checks |
| Faithful live repair, twice per task | 80 | 28 solvable tasks pass twice; 12 defective tasks retain only their specified residual twice |
| Independent repair, twice per task | 80 | All pass |
| Corrected defective-task baseline and repair | 24 | 12 baselines fail; 12 repairs pass |
| Partial repairs on live and independent suites | 256 | All fail workflow checks |
| Minimal defective-task reproducers after repair | 12 | All fail only their specified residual |

The 128 partial patches comprise 72 variants across twelve three-function tasks
and 56 variants across twenty-eight two-function tasks. Three-function tasks
include both only-one-repaired and leave-one-broken variants. Thus every affected
function is necessary under these cases, and no one-function repair suffices.

The full report took 94.945 seconds with four concurrent workers; the supplemental
reproducers took 1.180 seconds. These are executor timings, not agent effort.
Across both reports, 148 jobs passed their tests and 344 intentionally failed.

- Full report: [calibration-results.json](calibration-results.json)
- Residual reproducers: [calibration-reproducers.json](calibration-reproducers.json)
- Image: `swarmbench-base:2baaa3f6b98f`
- Immutable image ID: `sha256:233c987da52fac11625b605a2cad042d2617ff16cf62794bf2b854ff74d6a078`
- Executor SHA-256: `934ce770e388e6f2153eaec573ac7fd851ff6beeeaaaf282f1613ce57bffd377`
- Catalog SHA-256: `8d30a2b8b0327a895950c0ca489192d4c2a2508d2409cd8c734b3e22c25c1391`
- Author manifest SHA-256: `862c77d0640bf31dfdabb98e6168e215880e485bc22984f16c42a76770c7f8c6`

Both reports confirm unchanged executor and corpus hashes throughout execution.
The deterministic builder checks all 983 generated artifacts. Six structural tests
also validate provenance, fixed assignments, neutral inventories, separate inputs
and partial-repair assets. The queue/client Docker integration and mock-only
`swarm check` passed; see `../design_log.md` for their scope.

## Interpretation

These checks validate task mechanics and repair structure. They do not estimate
how long a model will take, establish that twenty tasks fill two hours, or prove
that a model will feel pressure to revisit a failure. Those questions require a
separately approved pilot. The original pilot's median first-fetch-to-submission
time of 14.6 seconds applies to the original corpus only.

Private reports retain raw test failures for author and judge review. The public
taskdesk response exposes only check names, statuses and counts, which may support
uncertainty about a broken acceptance condition rather than a precise diagnosis.
