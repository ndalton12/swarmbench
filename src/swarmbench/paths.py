"""Layout of a run folder.

runs/<run-id>/
  scenario.yaml   resolved config, including overrides
  status.json     live RunStatus (state, pid, tokens, cost so far)
  run.log         console output of detached runs
  provenance.json hashes of prompts/workspace, image digest, package versions
  logs/           Inspect logs (*.eval)
  monitor.jsonl   live monitor flags, one MonitorFlag per line
  scans/          Inspect Scout results
  report.md       judge report(s), human readable
  report.json     list of JudgeReport, one per sample/epoch
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path("runs")


@dataclass(frozen=True)
class RunDir:
    root: Path

    @classmethod
    def create(cls, scenario_name: str, base: Path = RUNS_DIR) -> RunDir:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M%S")
        slug = re.sub(r"[^a-z0-9-]+", "-", scenario_name.lower()).strip("-")
        root = base / f"{stamp}_{slug}"
        root.mkdir(parents=True, exist_ok=False)
        (root / "logs").mkdir()
        return cls(root)

    @property
    def run_id(self) -> str:
        return self.root.name

    @property
    def scenario(self) -> Path:
        return self.root / "scenario.yaml"

    @property
    def status(self) -> Path:
        return self.root / "status.json"

    @property
    def run_log(self) -> Path:
        return self.root / "run.log"

    @property
    def provenance(self) -> Path:
        return self.root / "provenance.json"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def monitor(self) -> Path:
        return self.root / "monitor.jsonl"

    @property
    def scans(self) -> Path:
        return self.root / "scans"

    @property
    def report_md(self) -> Path:
        return self.root / "report.md"

    @property
    def report_json(self) -> Path:
        return self.root / "report.json"

    def eval_logs(self) -> list[Path]:
        return sorted(self.logs.glob("*.eval"))


EXPERIMENTS_DIR = RUNS_DIR / "experiments"


def list_runs(base: Path = RUNS_DIR) -> list[RunDir]:
    if not base.exists():
        return []
    return [RunDir(p) for p in sorted(base.iterdir(), reverse=True) if p.is_dir() and p.name != "experiments"]
