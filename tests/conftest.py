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
    monkeypatch.setenv("SWARMBENCH_POLL", "0.1")  # supervisors, including background ones


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
    monkeypatch.setenv("SWARMBENCH_NO_DOTENV", "1")  # inherited by any `swarm` subprocess too
    # Inspect loads a .env file (searching up from the cwd) whenever an eval starts; with real
    # keys in the repo's .env that would undo the deletions below mid-test. Make it a no-op.
    import inspect_ai._eval.context
    import inspect_ai._eval.evalset
    import inspect_ai._util.dotenv

    for module in (inspect_ai._util.dotenv, inspect_ai._eval.context, inspect_ai._eval.evalset):
        monkeypatch.setattr(module, "init_dotenv", lambda: None, raising=False)
    for key in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "INSPECT_EVAL_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def pytest_configure(config):
    config.addinivalue_line("markers", "docker: needs a local Docker daemon (builds images, runs containers)")
    config.addinivalue_line("markers", "slow: takes seconds of real time (subprocesses, polling, sleeps)")


# Marked here rather than in each file, so the lists live in one place.
# Files that start real containers but only skip when Docker is missing:
_DOCKER_FILES = {"test_watch_docker.py", "test_watcher_docker.py", "test_docker.py"}
# Tests that wait in real time (background processes, polling loops, deliberate delays):
_SLOW_TESTS = {
    "test_judge_parallel.py::test_parallel_judging_is_much_faster",
    "test_screen.py::test_second_round_gives_top_third_more_runs",
    "test_screen.py::test_screen_end_to_end",
    "test_screen.py::test_reusing_a_screen_name_leaves_old_runs_out",
    "test_screen.py::test_stop_a_screen_by_name",
    "test_screen.py::test_drop_after_four_quiet_runs_but_leads_still_shown",
    "test_screen.py::test_budget_limits_the_screen",
    "test_cli.py::test_experiment_detached_then_list",
    "test_cli.py::test_experiment_foreground",
    "test_cli.py::test_hard_stop_kills_and_removes_containers",
    "test_cli.py::test_stop_experiment_stops_supervisor_and_runs",
    "test_cli.py::test_detached_run_finishes_in_background",
    "test_cli.py::test_ps_and_graceful_stop",
    "test_judge_model.py::test_experiment_warns_only_for_overlapping_combinations",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = item.nodeid.split("/")[-1]
        if item.path.name in _DOCKER_FILES:
            item.add_marker(pytest.mark.docker)
        if name in _SLOW_TESTS:
            item.add_marker(pytest.mark.slow)
