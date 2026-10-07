"""The sample-wide dollar ledger: concurrent calls can't overshoot max_cost."""

from __future__ import annotations

import anyio
from inspect_ai.model import ModelCost

from swarmbench.engine.costguard import MIN_OUTPUT, CostLedger

# $1 per million input tokens, $10 per million output tokens
PRICE = ModelCost(input=1.0, output=10.0, input_cache_write=1.25, input_cache_read=0.1)


def make(cap: float, spent: list[float], reasons: list[str]) -> CostLedger:
    return CostLedger(cap, price_of=lambda m: PRICE, spent=lambda: spent[0], on_cap=reasons.append)


async def test_concurrent_calls_near_the_cap_never_overshoot():
    spent = [0.0]
    reasons: list[str] = []
    ledger = make(0.10, spent, reasons)
    # each call: 10k input ($0.01) + up to 4k output ($0.04) = $0.05 reserved
    results: dict[int, int | None] = {}
    finish = {i: anyio.Event() for i in range(4)}

    async def call(i: int, actual: float) -> None:
        cap = await ledger.reserve("m", 10_000, 4_000)
        results[i] = cap
        if cap is not None:
            await finish[i].wait()
            spent[0] += actual  # the call completes: Inspect now counts its real cost

    async with anyio.create_task_group() as tg:
        for i in range(3):
            tg.start_soon(call, i, 0.03)
        await anyio.sleep(0.05)
        # two fit ($0.10); the third waits rather than overshooting
        assert results.get(0) == 4000 and results.get(1) == 4000 and 2 not in results
        finish[0].set()
        await anyio.sleep(0.05)
        # $0.03 spent + $0.05 outstanding: $0.02 left, so the third waits for a full allowance
        assert 2 not in results
        finish[1].set()
        await anyio.sleep(0.05)
        # alone now with $0.04 left: it goes, its reply capped to what fits
        assert results[2] is not None and results[2] < 4000
        assert spent[0] + 10_000 * 1e-6 + results[2] * 10e-6 <= 0.10 + 1e-9
        finish[2].set()
    assert ledger.outstanding == {} and not reasons


async def test_cap_reached_refuses_everything_after():
    spent = [0.0]
    reasons: list[str] = []
    ledger = make(0.02, spent, reasons)  # a small, screen-sized cap
    assert await ledger.reserve("m", 1_000, 1_000, key="a") == 1000
    ledger.release("a")
    spent[0] = 0.019  # nearly all spent: not even a minimal reply (MIN_OUTPUT) fits
    assert await ledger.reserve("m", 1_000, 1_000, key="b") is None
    assert ledger.reached and len(reasons) == 1 and "max_cost $0.02" in reasons[0]
    assert await ledger.reserve("m", 10, 10, key="c") is None  # final: everything after is refused
    assert MIN_OUTPUT * 10e-6 > 0.02 - 0.019 - 1_000e-6


async def test_no_cap_and_unpriced_models_are_not_blocked():
    assert await CostLedger(None).reserve("m", 10**9, 10**9) == 10**9
    ledger = CostLedger(0.01, price_of=lambda m: None, spent=lambda: 0.0)
    assert await ledger.reserve("x/unknown", 10**6, 100, key="k") == 100
    assert ledger.unpriced == {"x/unknown"}
