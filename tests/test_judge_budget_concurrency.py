"""Parallel part reviews each reserve their worst case. A call that would fit once the calls in
flight settle waits for them; it isn't refused (a real judging read only 8 of 10 parts while
spending $3.88 of an $8 cap)."""

from __future__ import annotations

import anyio
import pytest

from swarmbench.judge.budget import JudgeBudget, JudgeBudgetExhausted
from swarmbench.types import CostSummary


class FakeModel:
    def __init__(self, spend: list[float], cost: float):
        self.spend, self.cost, self.calls = spend, cost, 0

    def __str__(self) -> str:
        return "fake/model"

    async def generate(self, input, *args, **kwargs):
        await anyio.sleep(0.05)
        self.spend.append(self.cost)
        self.calls += 1
        return "ok"


def _budget(spend: list[float], cap: float, worst: float) -> JudgeBudget:
    return JudgeBudget(
        cap_usd=cap,
        spent_fn=lambda: CostSummary(usd=sum(spend), tokens=0),
        estimate_fn=lambda model, input, config: (worst, 10),
    )


def test_parallel_calls_wait_for_each_other_instead_of_being_refused():
    spend: list[float] = []
    budget = _budget(spend, cap=1.0, worst=0.6)  # two worst cases don't fit at once
    model = budget.guard(FakeModel(spend, cost=0.1))  # but each really costs 0.1

    async def main():
        async with anyio.create_task_group() as tg:
            for _ in range(4):
                tg.start_soon(model.generate, "x")

    anyio.run(main)
    assert model.calls == 4 and not budget.hit and not budget.held_back
    assert sum(spend) == pytest.approx(0.4)


def test_a_call_that_cannot_fit_even_alone_is_refused():
    spend: list[float] = [0.7]
    budget = _budget(spend, cap=1.0, worst=0.6)
    model = budget.guard(FakeModel(spend, cost=0.1))
    with pytest.raises(JudgeBudgetExhausted):
        anyio.run(model.generate, "x")
    assert budget.hit


def test_a_held_ticket_is_never_waited_on():
    """Room held by a part's answer ticket doesn't settle on its own, so nothing waits for it."""
    spend: list[float] = []
    budget = _budget(spend, cap=1.0, worst=0.6)
    assert budget.try_reserve(0.5, 10, record=False)  # a ticket
    model = budget.guard(FakeModel(spend, cost=0.1))
    async def main():
        with anyio.fail_after(2):
            await model.generate("x")

    with pytest.raises(JudgeBudgetExhausted):
        anyio.run(main)
