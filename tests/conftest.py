from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests import fake_launcher


def make_scenario(folder: Path, yaml_text: str | None = None) -> Path:
    """A minimal valid scenario folder."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scenario.yaml").write_text(
        yaml_text
        or "name: tiny\nswarm: {agents: 2, model: anthropic/claude-sonnet-5-5, token_budget: 200k}\nmax_cost: 2\n"
    )
    (folder / "prompt.md").write_text("Do the work.\n")
    (folder / "workspace").mkdir(exist_ok=True)
    (folder / "notes.md").write_text("Notes for the judge.\n")
    return folder


@pytest.fixture
def runs_base(tmp_path, monkeypatch) -> Path:
    """Runs go to a temporary folder; the working folder is temporary too."""
    base = tmp_path / "runs"
    monkeypatch.setenv("SWARMBENCH_RUNS", str(base))
    monkeypatch.chdir(tmp_path)
    return base


@pytest.fixture
def scenario(tmp_path) -> Path:
    return make_scenario(tmp_path / "scenarios" / "tiny")


@pytest.fixture
def fakes(monkeypatch):
    """Fake engine and judge, in this process and in any background process it starts."""
    from swarmbench import engine, judge
    from swarmbench.runner import procs

    monkeypatch.setattr(engine, "run_scenario", fake_launcher.fake_run_scenario)
    monkeypatch.setattr(judge, "judge_run", fake_launcher.fake_judge_run)
    launcher = str(Path(fake_launcher.__file__).resolve())
    monkeypatch.setattr(procs, "python_command", lambda *args: [procs.sys.executable, launcher, *args])
    monkeypatch.setenv("FAKE_RUN_SECONDS", "0.2")


def wait_for(condition, timeout: float = 20.0, interval: float = 0.1):
    """Poll until ``condition()`` is truthy; fail the test after ``timeout`` seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


@pytest.fixture(autouse=True)
def _no_real_model_keys(monkeypatch):
    """Tests must never reach a real model, even on a machine that has API keys."""
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "INSPECT_EVAL_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
