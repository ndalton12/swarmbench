"""Judge model calls run concurrently, bounded, in a fixed result order, within the cap."""

from __future__ import annotations

import os
import random
import time

import anyio
import pytest
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput, get_model

import swarmbench.judge as J
import swarmbench.judge.scanners as S
from swarmbench.judge import mock_answer
from swarmbench.judge.budget import JudgeBudget
from swarmbench.judge.extract import AgentView, SampleInputs
from swarmbench.paths import RunDir
from swarmbench.types import CostSummary
from tests.fixtures import build_mock_log


def _inputs(n_agents=3):
    agents = [
        AgentView(
            name=f"agent-{i}",
            messages=[ChatMessageUser(content="go"), ChatMessageAssistant(content=f"work {i}")],
        )
        for i in range(1, n_agents + 1)
    ]
    return SampleInputs(
        scenario="s",
        run_id="r",
        sample_id=1,
        epoch=1,
        agents=agents,
        foreign=[],
        agents_meta=[],
        messages=[{"id": 1, "sender": "agent-1", "to": "all", "text": "hello"}],
        monitor_flags=[],
        bridge_summary={},
        bridge_uses=[],
        protected_hashes={},
        problems=[],
        agent_usage={},
        outcome="",
    )


class Tracker:
    def __init__(self, delay=0.0, jitter=0.0):
        self.delay, self.jitter = delay, jitter
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    def model(self):
        async def outputs(input, tools, tool_choice, config):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await anyio.sleep(self.delay + random.random() * self.jitter)
                prompt = "\n".join(str(getattr(m, "text", "")) for m in input)
                return ModelOutput.from_content("mockllm/model", mock_answer(prompt))
            finally:
                self.in_flight -= 1
                self.calls += 1

        return get_model("mockllm/model", custom_outputs=outputs)


def test_results_keep_a_fixed_order_whatever_finishes_first():
    expected = [(f"agent-{i}", s.key) for i in range(1, 4) for s in S.AGENT_SPECS]
    for _ in range(2):
        tracker = Tracker(delay=0.0, jitter=0.02)

        async def go(tracker: Tracker = tracker):
            return await S.run_agent_scanners(_inputs(), tracker.model(), limiter=S.make_limiter(8))

        hits = anyio.run(go)
        assert [(h.agent, h.key) for h in hits] == expected


def test_concurrency_is_bounded():
    tracker = Tracker(delay=0.02)

    async def go():
        return await S.run_agent_scanners(_inputs(), tracker.model(), limiter=S.make_limiter(4))

    anyio.run(go)
    assert 1 < tracker.max_in_flight <= 4


def test_cap_holds_under_concurrency():
    tracker = Tracker(delay=0.02)
    model = tracker.model()
    budget = JudgeBudget(
        cap_usd=1.0,
        spent_fn=lambda: CostSummary(
            tokens=0, usd=0.3 * tracker.calls
        ),  # spend appears only after a call ends
        estimate_fn=lambda m, i, c: (0.3, 100),
    )
    budget.guard(model)
    budget.start_sample()

    async def go():
        return await S.run_agent_scanners(_inputs(), model, budget=budget, limiter=S.make_limiter(8))

    hits = anyio.run(go)
    # reservations count calls still in flight, so concurrency can't overshoot the cap
    assert tracker.calls <= 3
    assert budget.hit
    assert all(h.error and h.error.startswith("judge budget ran out") for h in hits if h.level is None)


def _time_judge(tmp_path, concurrency, delay):
    rd = RunDir.create(f"demo-{concurrency}", base=tmp_path)
    build_mock_log(
        rd.logs,
        agent_texts={f"agent-{i}": f"work {i}" for i in range(1, 4)},
        messages=[{"id": 1, "sender": "agent-1", "to": "all", "text": "hello"}],
    )
    tracker = Tracker(delay=delay)
    model = tracker.model()

    async def go():
        original_models, original_conc = J._resolve_models, J._judge_concurrency
        J._resolve_models = lambda m, judge_model=None: J._Models(model, model, model, model)
        J._judge_concurrency = lambda advanced: concurrency
        try:
            start = time.perf_counter()
            await J._judge_async(rd, None, engine="scanners")
            return time.perf_counter() - start
        finally:
            J._resolve_models, J._judge_concurrency = original_models, original_conc

    return anyio.run(go), tracker.calls


@pytest.mark.skipif(
    bool(os.environ.get("PYTEST_XDIST_WORKER")),
    reason="wall-clock timing is unreliable while other tests share the CPU; concurrency itself is checked by max_in_flight above",
)
def test_parallel_judging_is_much_faster(tmp_path):
    # 0.2 s per call; the fixed overhead (reading the log, writing Scout results) is the same for both
    serial, calls_serial = _time_judge(tmp_path, 1, 0.2)
    parallel, calls_parallel = _time_judge(tmp_path, 8, 0.2)
    assert calls_serial == calls_parallel
    # Cache warming runs one call per transcript before fanning out, so the speedup is ~3x, not 4x+.
    assert parallel < serial / 2.5, (serial, parallel)
