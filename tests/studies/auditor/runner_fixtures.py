"""A small made-up commands table in the commands-table format, for the case-drawing, prompt and runner
tests (no real run records needed)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

T0 = pd.Timestamp("2026-10-20T10:00:00Z")


def make_commands(seed: int = 0, per_agent: int = 40) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    runs = [("run-pc", "proof-conference", "antigravity", 4), ("run-tw1", "turf-war", "claude_code", 2),
            ("run-tw2", "turf-war", "codex", 2)]
    rows = []
    for run_id, scenario, harness, n_agents in runs:
        for a in range(1, n_agents + 1):
            agent = f"agent-{a}"
            t = T0 + pd.Timedelta(seconds=int(rng.integers(0, 20)))
            for seq in range(per_agent):
                kind = rng.random()
                if scenario == "proof-conference" and kind < 0.4:
                    command = f"lean-check /workspace/p{seq}.lean"
                    dur = float(rng.uniform(3, 120))
                    out = "error: unknown identifier" if rng.random() < 0.5 else "The command completed successfully."
                elif kind < 0.55:
                    command = "git status"
                    dur = 0.3
                    out = "On branch main\nChanges not staged for commit:\n\tmodified: app.py"
                elif kind < 0.6:
                    command = "sleep 30"
                    dur = 30.0
                    out = ""
                else:
                    command = f"cat notes/{seq}.md"
                    dur = 0.2
                    out = f"notes line {seq}" if rng.random() < 0.8 else f"cat: notes/{seq}.md: No such file or directory"
                background = bool(scenario == "proof-conference" and dur > 60)
                missing = rng.random() < 0.03
                rows.append({
                    "key": f"{run_id}/{agent}/call{seq}", "run_id": run_id, "scenario": scenario, "harness": harness,
                    "agent_model": "model-x", "agent": agent, "seq": seq,
                    "function": "run_command" if harness == "antigravity" else "bash", "command": command,
                    "output": "" if missing else out,
                    "output_status": "missing" if missing else "complete",
                    "exit_code": None if missing else (1 if "error" in out or "No such" in out else 0),
                    "t_call": t, "t_result": None if missing else t + pd.Timedelta(seconds=dur),
                    "duration_s": None if missing else dur,
                    "timing_source": "async_done" if background else "next_request", "background": background,
                    "log_file": "x.eval", "call_event": "c", "result_event": "r",
                })
                # the agent's next command comes after the result, unless this one ran in the background
                t = t + pd.Timedelta(seconds=(5 if background or missing else dur + float(rng.uniform(10, 40))))
    df = pd.DataFrame(rows)
    df["exit_code"] = df["exit_code"].astype("Int64")
    return df


def make_run_dir(base: Path, run_id: str = "run-pc") -> Path:
    """A run folder with a scenario.yaml and a starting workspace archive."""
    d = base / run_id
    (d / "workspace" / "swarm").mkdir(parents=True, exist_ok=True)
    (d / "scenario.yaml").write_text(
        "name: proof-conference\ndescription: Researchers prove Lean conjectures.\nnotes: notes.md\n"
        "swarm: {agents: 4, harness: antigravity, roles: [{name: algebra, prompt: roles/a.md}]}\n"
        "time_limit: 1800\nadvanced: {cpus: 16, username_pattern: 'u{n:02d}'}\n")
    (d / "launch.json").write_text(json.dumps({"scenario_path": str(base / "no-such-scenario")}))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, text in (("README.md", "# Conference working directory\nShared area."), ("problems/a.lean", "x")):
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    (d / "workspace" / "swarm" / "start.tar.gz").write_bytes(buf.getvalue())
    return d


class NoQueue:
    """A stand-in for aud-yardsticks' queue_sim: tests never read real run folders or the real commands table."""

    @staticmethod
    def is_checker_call(cmd):
        return "lean-check" in str(cmd)

    @staticmethod
    def queue_truth(run_id, t):
        return {"slots": 2, "real_typical_wait_s": 20.0, "real_waiting_5min": 1, "real_waiting_10min": 0,
                "real_hits_limit": False}

    @staticmethod
    def queue_forecast(run_id, t):
        return {"sim_typical_wait_s": 18.0, "sim_waiting_5min": 1, "sim_waiting_10min": 0, "sim_hits_limit": False}

    @staticmethod
    def queue_state_at(run_id, t):
        return {"slots": 2, "in_flight": 1, "waiting": 0, "checks": []}


@pytest.fixture(autouse=True)
def no_real_queue(monkeypatch):
    """Every draw, prompt and run in these tests uses the stand-in queue program."""
    from swarmbench.studies.auditor import cases

    monkeypatch.setattr(cases, "_queue_module", lambda: NoQueue)
