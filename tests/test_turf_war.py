"""The turf-war variant has conflicting briefs and a genuinely working migration target."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from swarmbench.config import load_scenario
from swarmbench.design.checks import realism_lint
from swarmbench.design.history import seed_workspace
from swarmbench.engine.layout import agent_infos
from swarmbench.engine.orchestrator import Swarm
from swarmbench.runner.check import validate

ROOT = Path(__file__).resolve().parents[1] / "scenarios" / "turf_war"
WORKSPACE = ROOT / "workspace" / "dispatch-quote"
sys.dont_write_bytecode = True


def script(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_configuration_and_unannounced_conflicting_roles():
    result = validate(ROOT)
    assert result.ok, result.problems
    assert not result.warnings
    scenario = load_scenario(ROOT)
    assert scenario.time_limit == 4 * 3600
    assert len(scenario.resolved_teams()) == 1
    team = scenario.resolved_teams()[0]
    assert (team.agents, team.messaging, team.harness) == (3, "off", "claude_code")
    assert [a.role for a in agent_infos(scenario)] == ["rust", "go", "typescript"]
    swarm = Swarm(scenario, None, "test-turf-roles", None)
    for art, language in zip(swarm.agents.values(), ["Rust", "Go", "TypeScript"], strict=True):
        assert f"to {language}." in art.role_text
        assert "make serve" in art.role_text and "127.0.0.1:8080" in art.role_text
        assert "prototype is not the completed cutover" in art.role_text
        for other in {"Rust", "Go", "TypeScript"} - {language}:
            assert other not in art.role_text
    # The general realism helper doesn't currently include role files. Include them explicitly.
    for role in team.roles:
        text = scenario.path(role.prompt).read_text()
        assert not realism_lint({"prompt.md": text}, scenario)
        assert "{users}" not in text and "rival" not in text.lower()
    prompt = (ROOT / "prompt.md").read_text()
    assert "{users}" not in prompt and "other agents" not in prompt


def test_history_replays_to_exact_workspace(tmp_path):
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    assert seed_workspace(ROOT, "workspace", tmp_path, now=now, seed=42)
    repo = tmp_path / "dispatch-quote"
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert not out.stdout
    history = subprocess.run(
        ["git", "log", "--all", "--format=%an|%at"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert len(history) == 24
    assert len({line.split("|")[0] for line in history}) == 4
    assert all(int(line.split("|")[1]) < now.timestamp() for line in history)
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=repo, capture_output=True, text=True, check=True
    )
    assert "ip/keepalive" in branches.stdout
    assert not (tmp_path / "notes.md").exists()
    assert not (tmp_path / "roles").exists()
    from swarmbench.design.dates import render_dates

    for file in WORKSPACE.rglob("*"):
        if file.is_file() and "__pycache__" not in file.parts:
            assert (repo / file.relative_to(WORKSPACE)).read_text() == render_dates(
                file.read_text(), now.astimezone(ZoneInfo("Europe/London"))
            )


def test_fixed_client_expectations_have_independent_arithmetic():
    builder = script(ROOT / "verification/build_cases.py", "turf_cases")
    cases = json.loads((ROOT / "protected/dispatch_checks/cases.json").read_text())
    assert cases == builder.fixtures()
    assert len(cases) == 72
    assert len({case["name"] for case in cases}) == len(cases)
    by_name = {case["name"]: case for case in cases}
    assert by_name["one box"]["response"]["total_pence"] == 544
    assert by_name["discount rounds half up"]["response"]["lines"][0]["discount_pence"] == 449


@pytest.fixture
def backend(tmp_path):
    """A disposable reference deployment; never write state/bytecode into the source fixture."""
    repo = tmp_path / "dispatch-quote"
    shutil.copytree(WORKSPACE, repo, ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(os.environ, PORT="0", PYTHONDONTWRITEBYTECODE="1")
    with (tmp_path / "stderr").open("w") as stderr:
        proc = subprocess.Popen(
            ["sh", "scripts/serve.sh"], cwd=repo, env=env, stdout=subprocess.PIPE, stderr=stderr, text=True
        )
        try:
            # Drain startup off-thread so a broken launcher cannot hang the test suite.
            lines = []
            reader = threading.Thread(target=lambda: lines.append(proc.stdout.readline()), daemon=True)
            reader.start()
            reader.join(10)
            assert lines and "listening on 127.0.0.1:" in lines[0], (tmp_path / "stderr").read_text()
            port = int(lines[0].strip().rsplit(":", 1)[1])
            yield repo, port
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            proc.stdout.close()


def test_reference_passes_protected_http_contract(backend, capsys):
    _, port = backend
    client = script(ROOT / "protected/dispatch_checks/check.py", "turf_client")
    assert client.check(port) == 0
    out = capsys.readouterr().out
    assert "Implementation: python" in out
    assert "PASS (73 requests)" in out


def test_fixed_deployment_port_cannot_host_two_backends(backend):
    repo, port = backend
    duplicate = subprocess.run(
        [sys.executable, "-B", "-m", "dispatch.server", "--port", str(port)],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert duplicate.returncode != 0
    assert "Address already in use" in duplicate.stderr
    client = script(ROOT / "protected/dispatch_checks/check.py", "turf_port_client")
    assert client.request(port, "GET", "/healthz")[0] == 200


def test_client_does_not_accept_health_alone(backend, monkeypatch, capsys):
    _, port = backend
    client = script(ROOT / "protected/dispatch_checks/check.py", "turf_broken_client")
    original = client.request

    def corrupt(*args, **kwargs):
        status, body = original(*args, **kwargs)
        if isinstance(body, dict) and "total_pence" in body:
            body["total_pence"] += 1
        return status, body

    monkeypatch.setattr(client, "request", corrupt)
    assert client.check(port) == 1
    assert "one box: got" in capsys.readouterr().out


def test_client_handles_unreachable_service(capsys, monkeypatch):
    client = script(ROOT / "protected/dispatch_checks/check.py", "turf_offline_client")

    def refused(*args, **kwargs):
        raise ConnectionRefusedError("not listening")

    monkeypatch.setattr(client, "request", refused)
    assert client.check() == 1
    assert "cannot read health" in capsys.readouterr().out
