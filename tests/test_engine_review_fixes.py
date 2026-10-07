"""Dry-run model guard, run outcome, cumulative epoch cost, and the container lease."""

from __future__ import annotations

import subprocess
import time

import pytest
import yaml
from inspect_ai.hooks import BeforeModelGenerate
from inspect_ai.model import GenerateConfig

from swarmbench.config import load_scenario
from swarmbench.engine.dryrun import DryRunGuard, RealModelInDryRun, dry_run_scenario, set_dry_run
from swarmbench.engine.orchestrator import add_costs
from swarmbench.types import CostSummary
from tests.engine_helpers import make_scenario, requires_docker, run_mock


def test_dry_run_scenario_mocks_every_model_role(tmp_path):
    folder = make_scenario(
        tmp_path,
        teams=[{"name": "red", "model": "openai/gpt-5.5"}, {"name": "blue"}],
        encounter={"after": 60, "via": "file", "source": "notes.md", "path": "/workspace/x"},
        **{
            "swarm.model": "anthropic/claude-sonnet-5-5",
            "advanced.monitor_model": "anthropic/claude-haiku-4-5",
            "advanced.judge_model": "anthropic/claude-opus-5-5",
        },
    )
    dry = dry_run_scenario(load_scenario(folder))
    assert {t.model for t in dry.resolved_teams()} == {"mockllm/model"}
    assert dry.advanced.monitor_model == "mockllm/model" and dry.advanced.judge_model == "mockllm/model"
    assert dry.root == folder.resolve()


async def test_guard_refuses_real_models_during_dry_runs():
    def data(model: str) -> BeforeModelGenerate:
        return BeforeModelGenerate(
            model_name=model, input=[], tools=[], tool_choice="auto", config=GenerateConfig(), cache=None
        )

    guard = DryRunGuard()
    await guard.on_before_model_generate(data("anthropic/claude-haiku-4-5"))  # not a dry run: allowed
    set_dry_run(True)
    try:
        await guard.on_before_model_generate(data("mockllm/model"))
        with pytest.raises(RealModelInDryRun):
            await guard.on_before_model_generate(data("anthropic/claude-haiku-4-5"))
    finally:
        set_dry_run(False)


def test_add_costs_accumulates_epochs():
    a = CostSummary(tokens=10, usd=1.0, by_agent={"agent-1": 1.0}, by_model={"m": 1.0})
    b = CostSummary(tokens=5, usd=0.5, by_agent={"agent-1": 0.5}, by_model={"m": 0.5})
    total = add_costs([a, b])
    assert total.tokens == 15 and total.usd == 1.5 and total.by_agent["agent-1"] == 1.5
    assert add_costs([a, CostSummary(tokens=1, usd=None, unpriced_models=["x"])]).usd is None


@requires_docker
@pytest.mark.docker
def test_dry_run_with_monitor_model_and_two_epochs(tmp_path):
    folder = make_scenario(
        tmp_path,
        epochs=2,
        **{
            "swarm.agents": 1,
            "swarm.messaging": "off",
            "advanced.extra": {},
            "advanced.monitor_model": "anthropic/claude-haiku-4-5",
        },
    )
    # an ambiguous-looking call, so the monitor would consult its model
    script = [
        ("shell", "kill -0 1 2>/dev/null; curl -s http://localhost:9 || true; echo probe"),
        ("final", "ok"),
    ]
    sample, run_dir, _ = run_mock(folder, tmp_path, {"agent-1": script})

    written = yaml.safe_load(run_dir.scenario.read_text())
    assert written["advanced"]["monitor_model"] == "mockllm/model"
    assert written["swarm"]["model"] == "mockllm/model"
    assert not any("real model" in p for p in sample.store["swarm_problems"])
    outcome = sample.metadata["swarm_outcome"]
    assert outcome["ok"] and outcome["outcome"] == "ok" and outcome["agents"] == {"agent-1": "finished"}

    from inspect_ai.log import read_eval_log

    log = read_eval_log(str(run_dir.eval_logs()[0]))
    assert len(log.samples or []) == 2
    status = yaml.safe_load(run_dir.status.read_text())
    per_epoch = [sum(u.total_tokens for u in s.model_usage.values()) for s in log.samples or []]
    # live status is cumulative across epochs
    assert status["swarm_cost"]["tokens"] == sum(per_epoch), (status["swarm_cost"], per_epoch)


@requires_docker
@pytest.mark.docker
def test_container_stops_when_lease_lapses(tmp_path):
    from swarmbench.engine.image import build_base_image

    image = build_base_image()
    name = f"sb-lease-test-{int(time.time())}"
    # lease 3 s, first grace 4 s: nobody renews it, so init kills everything and exits
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--tmpfs",
            "/var/backups",
            image,
            "/sbin/init",
            "3",
            "4",
        ],
        check=True,
        capture_output=True,
    )
    try:
        subprocess.run(["docker", "exec", "-d", name, "sleep", "1000"], check=True)
        deadline = time.time() + 40
        running = True
        while time.time() < deadline:
            out = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True
            )
            running = out.stdout.strip() == "true"
            if not running:
                break
            time.sleep(1)
        assert not running, "container still running after its lease lapsed"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@requires_docker
@pytest.mark.docker
def test_container_lives_while_lease_is_renewed(tmp_path):
    from swarmbench.engine.image import build_base_image

    image = build_base_image()
    name = f"sb-lease-ok-{int(time.time())}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--tmpfs",
            "/var/backups",
            image,
            "/sbin/init",
            "3",
            "4",
        ],
        check=True,
        capture_output=True,
    )
    try:
        for _ in range(10):
            subprocess.run(["docker", "exec", name, "/bin/touch", "/var/backups/.lease"], check=True)
            time.sleep(1)
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True
        )
        assert out.stdout.strip() == "true"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
