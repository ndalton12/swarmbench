#!/usr/bin/env python3
"""Run trusted reference calibration through the same isolated grading boundary.

This never executes project code on the host. It constructs immutable inputs and
calls the engine's disposable executor. No model calls or external network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services/taskdesk"


def suite_catalog(task_id: str, variant: str, destination: Path) -> Path:
    """Prepare author-selected suites; this is never a live client operation."""
    catalog = json.loads((SERVICE / "catalog.json").read_text())
    metadata = json.loads((ROOT / "verification/task_manifest.json").read_text())
    task = catalog["tasks"][task_id]
    base = destination / "tasks" / task_id
    shutil.copytree(SERVICE / "tasks" / task_id, base)
    if variant != "live":
        source = ROOT / "verification" / metadata["tasks"][task_id][variant + "_dir"] / "test_task.py"
        content = source.read_bytes()
        (base / "hidden/test_task.py").write_bytes(content)
        task["asset_hashes"]["hidden/test_task.py"] = hashlib.sha256(content).hexdigest()
        task["expected_tests"] = metadata["tasks"][task_id][variant + "_tests"]
        serialized = json.dumps(task["asset_hashes"], indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        task["version"] = hashlib.sha256(serialized.encode()).hexdigest()
    catalog["tasks"] = {task_id: task}
    catalog["assignments"] = {}
    (destination / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", action="append", help="Stable task ID; default all 40.")
    parser.add_argument(
        "--reproducers-only",
        action="store_true",
        help="Run only the 12 minimal defective-task reproducers after faithful repair.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, 5),
        default=4,
        help="Bounded concurrent disposable jobs (1..4; default4).",
    )
    parser.add_argument("--image", help="Already built runtime image; no network is used by jobs.")
    parser.add_argument(
        "--output", type=Path, required=True, help="Write the author calibration report here."
    )
    args = parser.parse_args()
    # Imported only when explicitly invoked, never by structural pytest collection.
    from swarmbench.engine import service_jobs

    execute_task = service_jobs.execute_task
    selected_image = args.image or service_jobs.runtime_image()
    executor_path = Path(service_jobs.__file__).resolve()
    executor_sha256 = hashlib.sha256(executor_path.read_bytes()).hexdigest()
    image_id = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", selected_image],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    metadata = json.loads((ROOT / "verification/task_manifest.json").read_text())
    task_ids = args.task or [
        task_id
        for task_id, task in metadata["tasks"].items()
        if not args.reproducers_only or task["classification"] == "broken"
    ]
    unknown = set(task_ids) - set(metadata["tasks"])
    if unknown:
        parser.error(f"unknown tasks: {sorted(unknown)}")
    report = {
        "schema_version": 1,
        "kind": "minimal_reproducers" if args.reproducers_only else "full_calibration",
        "executor": "swarmbench.engine.service_jobs.execute_task",
        "image": selected_image,
        "image_id": image_id,
        "executor_source_sha256": executor_sha256,
        "executor_source": "src/swarmbench/engine/service_jobs.py",
        "model_calls": 0,
        "started_utc": datetime.now(UTC).isoformat(),
        "catalog_sha256": hashlib.sha256((SERVICE / "catalog.json").read_bytes()).hexdigest(),
        "verification_manifest_sha256": hashlib.sha256(
            (ROOT / "verification/task_manifest.json").read_bytes()
        ).hexdigest(),
        "job_count": 0,
        "requested_task_count": len(task_ids),
        "complete": False,
        "passed": False,
        "tasks": {},
        "errors": [],
    }
    report["workers"] = args.workers
    start = time.monotonic()

    def run_task(task_id):
        meta = metadata["tasks"][task_id]
        reference = (ROOT / "verification" / meta["repair"]).read_bytes()
        plan = [
            ("live", "baseline", False, b"", None),
            ("live", "repair", meta["classification"] == "solvable", reference, None),
            ("live", "repair_repeat", meta["classification"] == "solvable", reference, None),
            ("independent", "repair", True, reference, None),
            ("independent", "repair_repeat", True, reference, None),
        ]
        if meta["classification"] == "broken":
            plan += [
                ("corrected", "baseline", False, b"", None),
                ("corrected", "repair", True, reference, None),
            ]
        for ablation in meta["ablations"]:
            patch = (ROOT / "verification" / ablation["patch"]).read_bytes()
            name = "ablation_" + ablation["mode"] + "_" + ablation["function"]
            plan.extend((variant, name, False, patch, ablation) for variant in ("live", "independent"))
        if args.reproducers_only:
            if meta["classification"] != "broken":
                raise ValueError(f"{task_id} has no defective-task reproducer")
            plan = [("reproducer", "repair", False, reference, None)]
        task_report = {"classification": meta["classification"], "checks": []}
        errors = []
        for variant, repair, expected, submitted, ablation in plan:
            with tempfile.TemporaryDirectory(
                prefix="rl-v2-calibration-", dir=Path(tempfile.gettempdir()).resolve()
            ) as temp:
                service = suite_catalog(task_id, variant, Path(temp))
                began = time.monotonic()
                result = execute_task(service, task_id, submitted, image=selected_image)
                selected = json.loads((service / "catalog.json").read_text())["tasks"][task_id]
                failure_methods = set(
                    re.findall(r"^(?:FAIL|ERROR): ([A-Za-z0-9_]+)", result.get("feedback", ""), re.MULTILINE)
                )
                reasons = []
                if result.get("tests_run") != len(selected["expected_tests"]):
                    reasons.append("suite did not run its complete expected test count")
                if sorted(result.get("inventory", [])) != sorted(selected["expected_tests"]):
                    reasons.append("suite inventory differs from the selected manifest")
                if repair == "baseline" or ablation:
                    field = "independent_workflow_tests" if variant == "independent" else "workflow_tests"
                    workflow_methods = {name.rsplit(".", 1)[-1] for name in meta[field]}
                    if not failure_methods.intersection(workflow_methods):
                        reasons.append("incomplete repair did not fail the intended coupled workflow")
                elif variant in {"live", "reproducer"} and meta["classification"] == "broken":
                    if failure_methods != {meta["defect_test"].rsplit(".", 1)[-1]}:
                        reasons.append("faithful repair did not leave exactly its documented residual defect")
                check = {
                    "suite": variant,
                    "patch": repair,
                    "expected_pass": expected,
                    "failure_methods": sorted(failure_methods),
                    "calibration_errors": reasons,
                    "duration_seconds": round(time.monotonic() - began, 3),
                    "result": result,
                }
                if ablation:
                    check["repaired_functions"] = ablation["repaired_functions"]
                    check["remaining_functions"] = ablation["remaining_functions"]
                task_report["checks"].append(check)
                errors.extend(f"{task_id}/{variant}/{repair}: {reason}" for reason in reasons)
                if (result.get("status") == "passed") != expected or result.get("status") not in {
                    "passed",
                    "failed",
                }:
                    errors.append(f"{task_id}/{variant}/{repair}: {result.get('status')} expected {expected}")
        return task_id, task_report, errors

    def record_progress():
        report["duration_seconds"] = round(time.monotonic() - start, 3)
        report["executor_source_unchanged"] = (
            hashlib.sha256(executor_path.read_bytes()).hexdigest() == executor_sha256
        )
        report["corpus_unchanged"] = (
            hashlib.sha256((SERVICE / "catalog.json").read_bytes()).hexdigest() == report["catalog_sha256"]
            and hashlib.sha256((ROOT / "verification/task_manifest.json").read_bytes()).hexdigest()
            == report["verification_manifest_sha256"]
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        temporary.replace(args.output)

    pool = ThreadPoolExecutor(max_workers=args.workers)
    futures = {pool.submit(run_task, task_id): task_id for task_id in task_ids}
    try:
        for future in as_completed(futures):
            task_id, task_report, errors = future.result()
            report["tasks"][task_id] = task_report
            report["job_count"] += len(task_report["checks"])
            report["errors"].extend(errors)
            record_progress()
            print(
                f"{task_id}: {len(task_report['checks'])} isolated checks; {len(errors)} errors", flush=True
            )
            if not report["executor_source_unchanged"] or not report["corpus_unchanged"]:
                report["errors"].append(
                    "Executor or corpus changed during calibration; repeat from stable inputs."
                )
                for pending in futures:
                    pending.cancel()
                break
    except BaseException:
        for pending in futures:
            pending.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        record_progress()
    report["complete"] = len(report["tasks"]) == len(task_ids)
    report["passed"] = report["complete"] and not report["errors"]
    report["finished_utc"] = datetime.now(UTC).isoformat()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if report["errors"]:
        print("\n".join(report["errors"]), file=sys.stderr)
        return 1
    print(f"All {len(task_ids)} tasks passed isolated reference calibration; no model calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
