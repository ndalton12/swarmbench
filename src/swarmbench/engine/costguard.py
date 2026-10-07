"""One dollar ledger per sample, so concurrent model calls can't overshoot ``max_cost``.

Inspect enforces ``cost_limit`` from completed usage, so several long requests sent at
the same moment could all pass its check and together overshoot. Every model call an
agent makes (through a bridge, or react's own) first reserves a conservative estimate:
its input tokens priced as uncached input, plus its output allowance at the output
price. A call is sent only if ``spent + outstanding + estimate <= cap``. While other
calls are in flight it waits for room; on its own, it may have its output capped to
fit; if even a minimal reply won't fit, the cap is reached: the call is refused and the
whole run winds down cleanly. Reservations are released when the call finishes (or
fails); actual spend is then read from Inspect's own accounting, so they reconcile.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import anyio
from inspect_ai.model import ModelCost

MIN_OUTPUT = 1024
"""Below room for this many output tokens, the dollar cap counts as reached."""


def _default_spent() -> float:
    from inspect_ai.model._model import sample_total_cost

    return sample_total_cost()


def _default_price(model: str) -> ModelCost | None:
    from swarmbench.costs import price_of

    return price_of(model)


class CostLedger:
    def __init__(
        self,
        cap: float | None,
        *,
        price_of: Callable[[str], ModelCost | None] = _default_price,
        spent: Callable[[], float] = _default_spent,
        on_cap: Callable[[str], None] | None = None,
    ) -> None:
        self.cap = cap
        self.price_of = price_of
        self.spent = spent
        self.on_cap = on_cap
        self.outstanding: dict[Any, float] = {}
        self.reached = False
        self.unpriced: set[str] = set()
        self._lock: anyio.Lock | None = None
        self._released: anyio.Event | None = None

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        price = self.price_of(model)
        if price is None:
            self.unpriced.add(model)
            return None
        return (input_tokens * price.input + output_tokens * price.output) / 1_000_000

    def _release(self, key: Any) -> None:
        if self.outstanding.pop(key, None) is not None and self._released is not None:
            self._released.set()
            self._released = anyio.Event()

    def _reach(self, why: str) -> None:
        if not self.reached:
            self.reached = True
            if self.on_cap is not None:
                self.on_cap(why)

    async def reserve(self, model: str, input_tokens: int, max_output: int, key: Any = None) -> int | None:
        """Reserve this call's estimated cost. Returns the output cap to use, or None if refused.

        ``key`` identifies the call (default: the current task, released when it finishes).
        """
        if self.cap is None:
            return max_output
        key = key if key is not None else asyncio.current_task()
        if self._lock is None:
            self._lock, self._released = anyio.Lock(), anyio.Event()
        price = self.price_of(model)
        if price is None:
            self.unpriced.add(model)
            return max_output  # an unpriced model can't be estimated (prices are checked before launch)
        while True:
            assert self._released is not None
            async with self._lock:
                if self.reached:
                    return None
                spent = self.spent()
                others = sum(v for k, v in self.outstanding.items() if k is not key)
                input_cost = input_tokens * price.input / 1_000_000
                per_output = price.output / 1_000_000
                room = self.cap - spent - input_cost
                if room < MIN_OUTPUT * per_output:  # not even a minimal reply fits, alone
                    self._reach(f"max_cost ${self.cap:.2f} reached (${spent:.4f} spent)")
                    return None
                headroom = room - others
                full = max_output * per_output
                # with others in flight, wait for a full allowance; alone, cap the reply to fit
                if headroom >= (full if others else MIN_OUTPUT * per_output):
                    cap = max_output if per_output == 0 else min(max_output, int(headroom / per_output))
                    if key not in self.outstanding and isinstance(key, asyncio.Task):
                        key.add_done_callback(self._release)
                    self.outstanding[key] = input_cost + cap * per_output
                    return cap
                released = self._released
            await released.wait()

    def release(self, key: Any) -> None:
        self._release(key)


def guarded_model(inner: Any, ledger: CostLedger) -> Any:
    """``inner`` (an Inspect Model), with every generate call reserved against ``ledger``.

    Used for react agents, whose calls go straight to the model rather than through a
    bridge. A refused call returns an empty reply, which ends the agent's turn.
    """
    from inspect_ai.model import GenerateConfig, Model, ModelOutput

    from .bridgefilter import DEFAULT_OUTPUT_RESERVE, STOPPED_MARK

    class GuardedModel(Model):
        async def generate(self, input, tools=[], tool_choice=None, config=GenerateConfig(), *args, **kwargs):  # noqa: B006, B008 - mirrors Model.generate; type: ignore[no-untyped-def,override]
            messages = [input] if isinstance(input, str) else list(input)
            chars = sum(len(m) if isinstance(m, str) else len(m.model_dump_json()) for m in messages)
            est_in = chars // 3 + 300 * len(tools or [])
            max_out = config.max_tokens or self.config.max_tokens or DEFAULT_OUTPUT_RESERVE
            key = object()
            cap = await ledger.reserve(str(self), est_in, max_out, key=key)
            if cap is None:
                output = ModelOutput.from_content(model=str(self), content="", stop_reason="stop")
                output.message.metadata = {STOPPED_MARK: "max_cost"}
                return output
            try:
                if cap < max_out:
                    config = config.merge(GenerateConfig(max_tokens=cap))
                return await super().generate(input, tools, tool_choice, config, *args, **kwargs)
            finally:
                ledger.release(key)

    return GuardedModel(inner.api, inner.config, getattr(inner, "model_args", None))
