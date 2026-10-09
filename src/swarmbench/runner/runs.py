"""One run: resolve the scenario, create its folder, run the swarm and the judge.

A run can execute in the current process (``swarm run``) or in a detached background
process (``swarm run --detach`` and experiments). Either way the work is done by
``execute(run_dir)``, which reads what to run from ``launch.json`` in the run folder.
"""

from __future__ import annotations

import json
import os
import re
import signal
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from swarmbench.config import Scenario, load_scenario
from swarmbench.paths import RUNS_DIR, RunDir
from swarmbench.runner import procs
from swarmbench.status import StatusWriter, read_status
from swarmbench.types import JudgeReport, RunStatus, now

MOCK_MODEL = "mockllm/model"
ACTIVE_STATES = ("starting", "running", "judging")
VERDICT_ORDER = ["none", "minor", "concerning", "severe"]

# Settings under ``swarm.`` can also be set per team. A command-line flag or an experiment's
# varied setting must beat team settings, so it is removed from every team as well.
TEAM_FIELDS = {"agents", "model", "effort", "harness", "token_budget", "messaging", "delivery"}


def runs_base() -> Path:
    """Where run folders go: ``$SWARMBENCH_RUNS`` or ``runs/``."""
    return Path(os.environ.get("SWARMBENCH_RUNS", str(RUNS_DIR)))


class Launch(BaseModel):
    """What a run was asked to do. Saved as launch.json so a background process can pick it up."""

    scenario_path: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    judge_model: str | None = None
    experiment: str | None = None
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict)


def launch_file(run_dir: RunDir) -> Path:
    return run_dir.root / "launch.json"


def stop_file(run_dir: RunDir) -> Path:
    """Written by ``swarm stop``. The engine checks it every second and winds the agents down
    cleanly (its text is the reason). The run checks it again once the swarm has finished,
    and then skips judging."""
    return run_dir.root / "stop_requested"


def request_stop(run_dir: RunDir, reason: str = "stopped by request") -> None:
    if not stop_file(run_dir).exists():
        stop_file(run_dir).write_text(reason)


def read_launch(run_dir: RunDir) -> Launch:
    return Launch.model_validate_json(launch_file(run_dir).read_text())


def scenario_file(path: str | Path) -> Path:
    path = Path(path)
    return path / "scenario.yaml" if path.is_dir() else path


def build_overrides(scenario_path: str | Path, settings: dict[str, Any]) -> dict[str, Any]:
    """Turn flags or varied settings (dotted keys) into ``load_scenario`` overrides.

    Keys with a None value are dropped. For ``swarm.<field>`` keys that teams can also set,
    the field is removed from every team too, so the override applies to all of them.
    """
    overrides = {k: v for k, v in settings.items() if v is not None}
    team_keys = {k.split(".", 1)[1] for k in overrides if k.startswith("swarm.")} & TEAM_FIELDS
    if not team_keys:
        return overrides
    teams = overrides.get("teams")
    if teams is None:
        file = scenario_file(scenario_path)
        data = (yaml.safe_load(file.read_text()) or {}) if file.exists() else {}
        teams = data.get("teams")
    if teams:
        overrides["teams"] = [{k: v for k, v in t.items() if k not in team_keys} for t in teams]
    return overrides


def resolve(scenario_path: str | Path, settings: dict[str, Any] | None = None) -> tuple[Scenario, dict]:
    """Load a scenario with flags applied. Returns the scenario and the overrides used."""
    overrides = build_overrides(scenario_path, settings or {})
    return load_scenario(scenario_path, overrides), overrides


def new_run_dir(scenario_name: str, base: Path | None = None) -> RunDir:
    """A fresh run folder. Adds -2, -3, ... if another run started in the same second."""
    base = base or runs_base()
    try:
        return RunDir.create(scenario_name, base)
    except FileExistsError:
        pass
    stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M%S")
    slug = re.sub(r"[^a-z0-9-]+", "-", scenario_name.lower()).strip("-")
    for n in range(2, 1000):
        root = base / f"{stamp}_{slug}-{n}"
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        (root / "logs").mkdir()
        return RunDir(root)
    raise RuntimeError("could not create a run folder")


def prepare(scenario: Scenario, launch: Launch, base: Path | None = None) -> RunDir:
    """Create the run folder, write launch.json and a first status.json."""
    run_dir = new_run_dir(scenario.name, base)
    launch_file(run_dir).write_text(launch.model_dump_json(indent=2))
    StatusWriter(
        run_dir,
        RunStatus(
            run_id=run_dir.run_id,
            scenario=scenario.name,
            experiment=launch.experiment,
            settings=launch.settings,
            agents_total=sum(t.agents for t in scenario.resolved_teams()),
        ),
    )
    return run_dir


def start_detached(run_dir: RunDir) -> tuple[int, float]:
    """Run ``execute(run_dir)`` in a background process. Output goes to run.log.

    Returns the process's pid and start time. Only the worker writes status.json from here
    on (it records its own pid first thing), so the two never race on that file.
    """
    return procs.spawn_detached(procs.python_command("_worker", str(run_dir.root)), run_dir.run_log)


class _StopRequested:
    """Turns the first SIGINT or SIGTERM into KeyboardInterrupt; later ones are ignored,
    so a second stop request can't interrupt the clean shutdown."""

    def __init__(self) -> None:
        self.requested = False

    def __call__(self, signum: int, frame: Any) -> None:
        if self.requested:
            print(f"[swarm] signal {signum} ignored: already stopping", flush=True)
            return
        self.requested = True
        print(f"[swarm] signal {signum}: stopping the run", flush=True)
        raise KeyboardInterrupt

    def install(self) -> None:
        signal.signal(signal.SIGINT, self)
        signal.signal(signal.SIGTERM, self)


def worst_verdict(reports: list[JudgeReport]) -> str | None:
    verdicts = [r.verdict for r in reports]
    return max(verdicts, key=VERDICT_ORDER.index) if verdicts else None


def worst_report(reports: list[JudgeReport]) -> JudgeReport | None:
    return max(reports, key=lambda r: VERDICT_ORDER.index(r.verdict)) if reports else None


def read_reports(run_dir: RunDir) -> list[JudgeReport]:
    try:
        data = json.loads(run_dir.report_json.read_text())
    except (FileNotFoundError, ValueError):
        return []
    items = data if isinstance(data, list) else [data]
    out = []
    for item in items:
        try:
            out.append(JudgeReport.model_validate(item))
        except ValueError:
            continue
    return out


def execute(
    run_dir: RunDir, handle_signals: bool = True, progress: Callable[[str], None] | None = None
) -> RunStatus:
    """Run the swarm, then the judge, keeping status.json up to date. Returns the final status.

    Never raises for a failed run: the error is recorded in the status instead.
    A SIGINT or SIGTERM stops the run cleanly (state ``stopped``) and skips judging.
    ``progress`` is called with ``"running"`` and ``"judging"`` as the run moves on.
    """
    tell = progress or (lambda phase: None)
    from swarmbench import engine, judge

    launch = read_launch(run_dir)
    existing = read_status(run_dir)
    status = StatusWriter(run_dir, existing or RunStatus(run_id=run_dir.run_id, scenario="?"))
    status.update(pid=os.getpid(), pid_started=procs.start_time(os.getpid()), force=True)

    stop = _StopRequested()
    if handle_signals:
        stop.install()

    try:
        scenario = load_scenario(launch.scenario_path, launch.overrides)
        if stop_file(run_dir).exists():
            raise KeyboardInterrupt  # stopped before it started
        status.update(state="running", scenario=scenario.name, force=True)
        tell("running")
        logs = engine.run_scenario(scenario, run_dir, status, dry_run=launch.dry_run) or []
        if stop.requested or stop_file(run_dir).exists():
            raise KeyboardInterrupt
        logs = [Path(p) for p in logs] or run_dir.eval_logs()
        if not logs:
            raise RuntimeError("the swarm finished without writing an Inspect log")
        _settle(run_dir, status, [])
        problems, notes = log_problems(logs)
        status.update(state="judging", force=True)
        tell("judging")
        judge_model = MOCK_MODEL if launch.dry_run else launch.judge_model
        reports = judge.judge_run(run_dir, model=judge_model)
        _settle(run_dir, status, reports)
        if problems:
            # Judged, but not a clean run: say so rather than reporting "done".
            status.update(state="failed", finished=now(), error=_join(problems), force=True)
        else:
            # A note (e.g. stopped early by the monitor) is kept in ``error`` as a warning.
            status.update(state="done", finished=now(), error=_join(notes) or None, force=True)
    except KeyboardInterrupt:
        _settle(run_dir, status, [])
        status.update(state="stopped", finished=now(), error="stopped by request", force=True)
    except NotImplementedError as e:
        _settle(run_dir, status, [])
        where = traceback.extract_tb(e.__traceback__)[-1]
        status.update(
            state="failed",
            finished=now(),
            error=f"not implemented yet: {where.name} in {Path(where.filename).parent.name}",
            force=True,
        )
    except Exception as e:
        traceback.print_exc()
        _settle(run_dir, status, [])
        status.update(state="failed", finished=now(), error=f"{type(e).__name__}: {e}", force=True)
    finally:
        if handle_signals:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
    return status.status


def _join(items: list[str]) -> str:
    more = f" (and {len(items) - 2} more)" if len(items) > 2 else ""
    return "; ".join(items[:2]) + more


def _settle(run_dir: RunDir, status: StatusWriter, reports: list[JudgeReport]) -> None:
    """Before a final status write: take the judge's fields, and settle the swarm's cost from
    every sample in the Inspect logs. The larger of the logged and live figures is kept, so a
    cost is never undercounted; an unpriced model makes it unknown."""
    from swarmbench import costs

    _take_judge_fields(run_dir, status, reports)
    logs = run_dir.eval_logs()
    settled = costs.eval_logs_cost(logs) if logs else None
    live = status.status.swarm_cost
    if settled is None:
        return
    if settled.usd is not None and live.usd is not None and live.usd > settled.usd:
        return
    status.update(swarm_cost=_with_agents(settled, live))


def _with_agents(settled, live):
    """Keep the engine's per-agent split, which the logs don't carry."""
    return settled.model_copy(update={"by_agent": live.by_agent}) if live.by_agent else settled


# Engine outcomes that end a sample early on purpose: worth a note, but the run still worked.
NOTE_OUTCOMES = {"monitor_stop", "user_stop"}
# Inspect sample limits whose cancellation of the swarm is a normal end (EvalSampleLimit.type).
ENDING_LIMITS = {"time", "working", "cost"}


def log_problems(paths: list[Path]) -> tuple[list[str], list[str]]:
    """What went wrong in a finished swarm, read from its Inspect logs: (problems, notes).

    Problems make the run "failed": a log that isn't "success", a sample error, or an engine
    outcome such as agent errors. Notes (stopped early by the monitor or a user) are shown
    but leave the run "done". The engine's outcome is sample metadata ``swarm_outcome`` =
    ``{"ok": bool, "outcome": "ok"|"agent_errors"|"monitor_stop"|"user_stop"|"sample_error",
    "problems": [...], "agents": {...}}``.
    """
    from inspect_ai.log import read_eval_log, read_eval_log_sample_summaries

    problems: list[str] = []
    notes: list[str] = []
    for path in paths:
        try:
            header = read_eval_log(str(path), header_only=True)
            summaries = read_eval_log_sample_summaries(str(path))
        except Exception as e:
            problems.append(f"could not read {Path(path).name}: {e}")
            continue
        if header.status != "success":
            detail = f": {header.error.message}" if header.error else ""
            problems.append(f"Inspect log {header.status}{detail}")
        multi = len(summaries) > 1
        for sample in summaries:
            where = f"epoch {sample.epoch}: " if multi else ""
            if sample.error:
                problems.append(f"{where}sample error: {sample.error.strip().splitlines()[0][:200]}")
            outcome = (sample.metadata or {}).get("swarm_outcome")
            limit = getattr(getattr(sample, "limit", None), "type", None)
            if isinstance(outcome, dict) and outcome.get("ok") is False:
                kind = str(outcome.get("outcome") or "problem")
                listed = [str(p) for p in outcome.get("problems") or []] or [kind.replace("_", " ")]
                if limit in ENDING_LIMITS and kind == "sample_error" and listed == ["sample error: cancelled"]:
                    # Inspect cancelled the swarm because a limit was reached: a normal end, not a failure.
                    notes.append(f"{where}ended at its {limit} limit")
                    continue
                bucket = notes if kind in NOTE_OUTCOMES else problems
                bucket.extend(f"{where}{p}" for p in listed)
    return problems, notes


def _take_judge_fields(run_dir: RunDir, status: StatusWriter, reports: list[JudgeReport]) -> None:
    """The judge writes verdict, headline and judge cost into status.json itself. Our
    in-memory copy would overwrite them, so pick them up (or fill them from the reports).
    Called before every final write, so a judge that fails part-way keeps its recorded cost."""
    on_disk = read_status(run_dir)
    fields: dict[str, Any] = {}
    if on_disk is not None:
        if on_disk.verdict is not None:
            fields["verdict"] = on_disk.verdict
        if on_disk.headline is not None:
            fields["headline"] = on_disk.headline
        fields["judge_cost"] = on_disk.judge_cost
    worst = worst_report(reports)
    if worst is not None:
        fields.setdefault("verdict", worst.verdict)
        fields.setdefault("headline", worst.headline)
    status.update(**fields)


_RUN_ID = re.compile(r"^\d{4}-(\d{2})-(\d{2})T(\d{2})(\d{2})\d{2}_(.+)$")


def short_id(run_id: str) -> str:
    """A compact name for tables: ``2026-10-07T132117_rival-swarms`` -> ``10-07 13:21 rival-swarms``.
    Commands accept it (in quotes) as well as the full id."""
    m = _RUN_ID.match(run_id)
    if not m:
        return run_id
    month, day, hour, minute, slug = m.groups()
    return f"{month}-{day} {hour}:{minute} {slug}"


def find_run(ref: str | Path, base: Path | None = None) -> RunDir:
    """A run folder from a path, a run id, a unique start of an id, the short name shown in
    tables (``10-07 13:21 rival-swarms``), or any unique part of an id."""
    path = Path(ref)
    if path.is_dir() and ((path / "status.json").exists() or (path / "logs").is_dir()):
        return RunDir(path)
    base = base or runs_base()
    ref = str(ref)
    if (base / ref).is_dir():
        return RunDir(base / ref)
    folders = [p for p in base.iterdir() if p.is_dir() and p.name != "experiments"] if base.exists() else []
    for match in (
        lambda name: name.startswith(ref),
        lambda name: short_id(name) == ref,
        lambda name: ref in name,
    ):
        matches = [p for p in folders if match(p.name)]
        if len(matches) == 1:
            return RunDir(matches[0])
        if len(matches) > 1:
            names = ", ".join(sorted(m.name for m in matches))
            raise FileNotFoundError(f"{ref!r} matches several runs: {names}")
    raise FileNotFoundError(f"no run {ref!r} (looked for a folder and in {base}/)")
