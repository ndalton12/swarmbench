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


def start_detached(run_dir: RunDir) -> int:
    """Run ``execute(run_dir)`` in a background process. Output goes to run.log."""
    pid, started = procs.spawn_detached(procs.python_command("_worker", str(run_dir.root)), run_dir.run_log)
    status = read_status(run_dir)
    if status is not None and status.pid is None:
        # The worker records its own pid as soon as it starts; this covers the gap before.
        StatusWriter(run_dir, status.model_copy(update={"pid": pid, "pid_started": started}))
    return pid


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


def execute(run_dir: RunDir, handle_signals: bool = True) -> RunStatus:
    """Run the swarm, then the judge, keeping status.json up to date. Returns the final status.

    Never raises for a failed run: the error is recorded in the status instead.
    A SIGINT or SIGTERM stops the run cleanly (state ``stopped``) and skips judging.
    """
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
        status.update(state="running", scenario=scenario.name, force=True)
        engine.run_scenario(scenario, run_dir, status, dry_run=launch.dry_run)
        if stop.requested or stop_file(run_dir).exists():
            raise KeyboardInterrupt
        status.update(state="judging", force=True)
        judge_model = MOCK_MODEL if launch.dry_run else launch.judge_model
        reports = judge.judge_run(run_dir, model=judge_model)
        _take_judge_fields(run_dir, status, reports)
        status.update(state="done", finished=now(), force=True)
    except KeyboardInterrupt:
        status.update(state="stopped", finished=now(), error="stopped by request", force=True)
    except NotImplementedError as e:
        where = traceback.extract_tb(e.__traceback__)[-1]
        status.update(
            state="failed",
            finished=now(),
            error=f"not implemented yet: {where.name} in {Path(where.filename).parent.name}",
            force=True,
        )
    except Exception as e:  # noqa: BLE001 - any failure is recorded, not raised
        traceback.print_exc()
        status.update(state="failed", finished=now(), error=f"{type(e).__name__}: {e}", force=True)
    finally:
        if handle_signals:
            signal.signal(signal.SIGINT, signal.default_int_handler)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
    return status.status


def _take_judge_fields(run_dir: RunDir, status: StatusWriter, reports: list[JudgeReport]) -> None:
    """The judge writes verdict, headline and judge cost into status.json itself. Our
    in-memory copy would overwrite them, so pick them up (or fill them from the reports)."""
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


def find_run(ref: str | Path, base: Path | None = None) -> RunDir:
    """A run folder from a path or a run id (also accepts a unique prefix of the id)."""
    path = Path(ref)
    if path.is_dir() and ((path / "status.json").exists() or (path / "logs").is_dir()):
        return RunDir(path)
    base = base or runs_base()
    if (base / str(ref)).is_dir():
        return RunDir(base / str(ref))
    matches = (
        [p for p in base.glob(f"{ref}*") if p.is_dir() and p.name != "experiments"] if base.exists() else []
    )
    if len(matches) == 1:
        return RunDir(matches[0])
    if len(matches) > 1:
        raise FileNotFoundError(f"{ref!r} matches several runs: {', '.join(sorted(m.name for m in matches))}")
    raise FileNotFoundError(f"no run {ref!r} (looked for a folder and in {base}/)")
