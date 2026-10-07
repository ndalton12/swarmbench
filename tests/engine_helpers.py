"""Helpers for engine tests that run real containers with the mock model."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from inspect_ai.log import EvalSample, read_eval_log

from swarmbench.config import load_scenario
from swarmbench.paths import RunDir
from swarmbench.status import StatusWriter
from swarmbench.types import RunStatus

FIXTURE = Path(__file__).parent / "fixtures" / "mini"
AGENT_NAME = re.compile(r"([a-z][a-z0-9_-]*-)?agent-\d+")


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


requires_docker = pytest.mark.skipif(not docker_available(), reason="docker not available")


def make_scenario(tmp_path: Path, **changes: Any) -> Path:
    """Copy the mini fixture and apply changes to its scenario.yaml (dotted keys allowed)."""
    folder = tmp_path / "scenario"
    shutil.copytree(FIXTURE, folder)
    data = yaml.safe_load((folder / "scenario.yaml").read_text())
    for key, value in changes.items():
        target = data
        *parents, leaf = key.split(".")
        for p in parents:
            target = target.setdefault(p, {})
        target[leaf] = value
    (folder / "scenario.yaml").write_text(yaml.safe_dump(data))
    return folder


def run_mock(
    scenario_dir: Path,
    tmp_path: Path,
    scripts: dict[str, list[Any]] | None = None,
    on_start: Any = None,
) -> tuple[EvalSample, RunDir, Any]:
    from swarmbench.engine import run_scenario
    from swarmbench.engine.mock import MockSwarmModel
    from swarmbench.engine.orchestrator import HOOKS, RunHooks

    scenario = load_scenario(scenario_dir)
    run_dir = RunDir.create(scenario.name, base=tmp_path / "runs")
    status = StatusWriter(run_dir, RunStatus(run_id=run_dir.run_id, scenario=scenario.name))
    mock = MockSwarmModel()
    HOOKS[run_dir.run_id] = RunHooks(mock=mock, scripts=scripts or {}, on_start=on_start)
    logs = run_scenario(scenario, run_dir, status, dry_run=True)
    assert logs, "no log written"
    log = read_eval_log(str(logs[0]), resolve_attachments=True)
    assert log.samples, f"no samples; status={log.status} error={log.error}"
    sample = log.samples[0]
    assert sample.error is None, sample.error.message
    return sample, run_dir, mock


def span_agents(sample: EvalSample) -> dict[str, str]:
    """span id -> agent name, for every span under an agent span."""
    spans = {e.id: e for e in sample.events if e.event == "span_begin"}
    out: dict[str, str] = {}
    for sid in spans:
        cur = sid
        while cur:
            s = spans.get(cur)
            if s is None:
                break
            if s.type == "agent" and AGENT_NAME.fullmatch(s.name):
                out[sid] = s.name
                break
            cur = s.parent_id
    return out


def info_events(sample: EvalSample, source: str) -> list[Any]:
    return [e for e in sample.events if e.event == "info" and e.source == source]


def model_inputs_text(sample: EvalSample, agent: str) -> str:
    """All text the model saw in an agent's span (tool results included)."""
    owners = span_agents(sample)
    parts = []
    for e in sample.events:
        if e.event == "model" and owners.get(e.span_id or "") == agent:
            parts.extend(m.text for m in e.input)
    return "\n".join(parts)


def tool_results_text(sample: EvalSample, agent: str) -> str:
    owners = span_agents(sample)
    return "\n".join(
        str(e.result) for e in sample.events if e.event == "tool" and owners.get(e.span_id or "") == agent
    )
