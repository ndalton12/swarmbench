"""A hard spending cap for the judge.

The cap is per sample (epoch): ``advanced.judge_max_cost`` dollars, or, when
that isn't set, ``costs.judge_allowance(max_cost)`` for a scenario with a
``max_cost`` and $10 otherwise. It is checked before every judge model call, so
spend can exceed it by at most the one call already in flight. When a model
has no price, a token cap stands in for the dollar cap.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from swarmbench.types import CostSummary

DEFAULT_CAP_NO_MAX_COST = 10.0
TOKEN_CAP_WHEN_UNPRICED = 2_000_000
JUDGE_MAX_OUTPUT_TOKENS = 2_000
JUDGE_MAX_RETRIES = 3
"""Retries of a failed judge call, made by the budget guard (each with its own reservation);
Inspect's internal retries are turned off for judge calls."""
RETRY_BASE_SECONDS = 3.0
JUDGE_TIMEOUT_SECONDS = 300


def default_cap(scenario: Any | None) -> float:
    """The judge's dollar cap per sample for a scenario."""
    advanced = getattr(scenario, "advanced", None)
    explicit = getattr(advanced, "judge_max_cost", None)
    if explicit is not None:
        return float(explicit)
    max_cost = getattr(scenario, "max_cost", None)
    if max_cost is not None:
        with contextlib.suppress(Exception):
            from swarmbench.costs import judge_allowance

            return float(judge_allowance(float(max_cost)))
    return DEFAULT_CAP_NO_MAX_COST


def usage_so_far() -> dict[str, Any]:
    """Inspect's running per-model usage for this process (the judge's own calls)."""
    with contextlib.suppress(Exception):
        from inspect_ai.model._model import model_usage_context_var

        return dict(model_usage_context_var.get())
    return {}


def cache_read_share(usage: dict[str, Any]) -> tuple[float | None, int, int]:
    """(share of input tokens read from the prompt cache, cache-read tokens, all input tokens).

    All input = uncached input + cache reads + cache writes. None when there was no input.
    """
    reads = sum(getattr(u, "input_tokens_cache_read", None) or 0 for u in usage.values())
    writes = sum(getattr(u, "input_tokens_cache_write", None) or 0 for u in usage.values())
    plain = sum(getattr(u, "input_tokens", 0) or 0 for u in usage.values())
    total = plain + reads + writes
    return (reads / total if total else None), reads, total


def cost_of(usage: dict[str, Any]) -> CostSummary:
    """Price usage through swarmbench.costs; unpriced models give usd=None, never $0."""
    if not usage:
        return CostSummary(tokens=0, usd=0.0)
    with contextlib.suppress(Exception):
        from swarmbench.costs import usage_cost

        return usage_cost(usage)
    total = sum(getattr(u, "total_tokens", 0) for u in usage.values())
    return CostSummary(
        tokens=total,
        input_tokens=sum(getattr(u, "input_tokens", 0) for u in usage.values()),
        output_tokens=sum(getattr(u, "output_tokens", 0) for u in usage.values()),
        usd=None,
        by_model={name: None for name in usage},
        unpriced_models=sorted(usage),
    )


class JudgeBudgetExhausted(RuntimeError):
    """Raised instead of making a judge model call that the cap doesn't allow."""


def _text_len(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_text_len(getattr(m, "text", m)) if not isinstance(m, str) else len(m) for m in value)
    return len(str(value or ""))


def estimate_call(model: Any, input: Any, config: Any = None) -> tuple[float | None, int]:
    """A conservative cost for one call: estimated input plus the maximum output,
    at the model's list price. ``usd`` is None when the model has no price."""
    tokens_in = _text_len(input) // 3 + 200  # ~3 characters per token, plus overhead
    max_out = getattr(config, "max_tokens", None) or getattr(
        getattr(model, "config", None), "max_tokens", None
    )
    max_out = int(max_out or JUDGE_MAX_OUTPUT_TOKENS)
    usd: float | None = None
    with contextlib.suppress(Exception):
        from swarmbench.costs import price_of

        price = price_of(str(model))
        if price is not None:
            usd = (tokens_in * price.input + max_out * price.output) / 1_000_000
    return usd, tokens_in + max_out


_ESSENTIAL: ContextVar[bool] = ContextVar("swarm_judge_essential", default=False)
"""True inside the judge's essential steps, which may spend the held-back part of the cap."""


@dataclass
class JudgeBudget:
    cap_usd: float
    token_cap: int = TOKEN_CAP_WHEN_UNPRICED
    spent_fn: Any = None
    """Returns the CostSummary spent so far (tests inject a fake)."""
    estimate_fn: Any = None
    """(model, input, config) -> (usd | None, tokens) for one call (tests inject a fake)."""
    hit: bool = False
    on_refusal: Any = None
    """Called with (model, input, message) when a call is refused (the call recorder uses it)."""
    _base: CostSummary = field(default_factory=lambda: CostSummary(tokens=0, usd=0.0))
    _reserved_usd: float = 0.0
    _reserved_tokens: int = 0
    hold_usd: float = 0.0
    """Kept back for the essential steps (two-pass judge): other calls can't spend it."""
    hold_tokens: int = 0
    held_back: bool = False
    """A call was refused because only the held-back part was left (the cap itself wasn't reached)."""

    # -- guarding every model call ---------------------------------------------

    def bind(self, models: Any) -> None:
        """Guard every judge model (scanner, screen, confirm, summarizer)."""
        seen: set[int] = set()
        for name in ("scanner", "screen", "confirm", "summarizer"):
            m = getattr(models, name, None)
            if m is not None and id(m) not in seen:
                seen.add(id(m))
                self.guard(m)

    def guard(self, model: Any) -> Any:
        """Wrap ``model.generate`` so every call (Scout's concurrent segments,
        retries and reductions included) reserves its worst-case cost first and is
        refused once the cap would be exceeded."""
        if getattr(model, "_swarm_budget", None) is self:
            return model
        # always wrap the unguarded call, so a later judge run doesn't stack ledgers
        original = getattr(model, "_swarm_original_generate", None) or model.generate
        model._swarm_original_generate = original
        budget = self

        async def generate(input: Any, *args: Any, **kwargs: Any) -> Any:
            from inspect_ai.model import GenerateConfig

            from swarmbench.judge.calls import ReplayedFailure, retryable

            # Inspect's own retries would happen inside one reservation (even after a completed
            # response), so they are off; retries happen here, each with a fresh reservation
            config = kwargs.get("config") or (args[2] if len(args) > 2 else None)
            kwargs["config"] = (config or GenerateConfig()).merge(GenerateConfig(max_retries=0))
            if len(args) > 2:
                args = args[:2] + args[3:]
            for attempt in range(JUDGE_MAX_RETRIES + 1):
                usd, tokens = (budget.estimate_fn or estimate_call)(model, input, config)
                if not budget.try_reserve(usd, tokens):
                    message = budget.gap() if budget.hit else budget.held_gap()
                    if budget.on_refusal is not None:  # recorded, so a replay refuses the same call
                        budget.on_refusal(model, input, message)
                    raise JudgeBudgetExhausted(message)
                try:
                    return await original(input, *args, **kwargs)
                except JudgeBudgetExhausted as exc:  # a refusal replayed from a recording
                    if str(exc) == budget.held_gap():
                        budget.held_back = True
                    else:
                        budget.hit = True
                    raise
                except Exception as exc:
                    if attempt >= JUDGE_MAX_RETRIES or not retryable(model, exc):
                        raise
                    if not isinstance(exc, ReplayedFailure):  # a replay doesn't wait
                        await budget.backoff(attempt)
                finally:
                    budget.release(usd, tokens)
            raise AssertionError("unreachable")

        model.generate = generate
        model._swarm_budget = self
        return model

    async def backoff(self, attempt: int) -> None:
        """Wait before retrying a rate-limited, overloaded or timed-out call: exponential with
        jitter, capped at a minute."""
        import random

        import anyio

        await anyio.sleep(min(60.0, RETRY_BASE_SECONDS * 2**attempt) * (0.5 + random.random() / 2))

    def try_reserve(self, usd: float | None, tokens: int) -> bool:
        spent_usd, spent_tokens = self.spent_this_sample()
        essential = _ESSENTIAL.get()
        if usd is not None and spent_usd is not None:
            need = spent_usd + self._reserved_usd + usd
            ok_full, limit = need <= self.cap_usd, self.cap_usd - (0.0 if essential else self.hold_usd)
            ok = need <= limit
        else:  # unpriced: the token cap stands in
            need_t = spent_tokens + self._reserved_tokens + tokens
            ok_full = need_t <= self.token_cap
            ok = need_t <= self.token_cap - (0 if essential else self.hold_tokens)
        if not ok:
            if ok_full:
                self.held_back = True  # only the essential steps' share is left
            else:
                self.hit = True
            return False
        self._reserved_usd += usd or 0.0
        self._reserved_tokens += tokens
        return True

    def release(self, usd: float | None, tokens: int) -> None:
        self._reserved_usd = max(0.0, self._reserved_usd - (usd or 0.0))
        self._reserved_tokens = max(0, self._reserved_tokens - tokens)

    def set_hold(self, usd: float | None, tokens: int) -> None:
        """Keep this much of the cap back for the essential steps (at most the cap itself)."""
        self.hold_usd = min(self.cap_usd, max(0.0, usd or 0.0))
        self.hold_tokens = min(self.token_cap, max(0, tokens))

    @contextlib.contextmanager
    def essential(self) -> Any:
        """Calls made inside may spend the held-back part of the cap."""
        token = _ESSENTIAL.set(True)
        try:
            yield
        finally:
            _ESSENTIAL.reset(token)

    def room(self) -> tuple[float | None, int]:
        """What's left of the cap now (dollars, or None when unpriced; tokens)."""
        spent_usd, spent_tokens = self.spent_this_sample()
        usd = None if spent_usd is None else self.cap_usd - spent_usd - self._reserved_usd
        return usd, self.token_cap - spent_tokens - self._reserved_tokens

    def held_gap(self) -> str:
        return ("the judge's budget for reading ran out: what's left of the cap is kept for the final review "
                "and the summary")

    def spent_total(self) -> CostSummary:
        return self.spent_fn() if self.spent_fn else cost_of(usage_so_far())

    def start_sample(self) -> None:
        """The cap is per sample: measure from here."""
        self._base = self.spent_total()
        self.hit = False
        self.held_back = False
        self.hold_usd, self.hold_tokens = 0.0, 0
        self._reserved_usd, self._reserved_tokens = 0.0, 0

    def spent_this_sample(self) -> tuple[float | None, int]:
        now = self.spent_total()
        tokens = now.tokens - self._base.tokens
        if now.usd is None or self._base.usd is None:
            return None, tokens
        return now.usd - self._base.usd, tokens

    def exhausted(self) -> bool:
        """True (and sticky for this sample) once the cap is reached."""
        if self.hit:
            return True
        usd, tokens = self.spent_this_sample()
        self.hit = (usd is not None and usd >= self.cap_usd) or (usd is None and tokens >= self.token_cap)
        return self.hit

    def gap(self) -> str:
        return (
            f"the judge's budget ran out (cap ${self.cap_usd:,.2f} per sample"
            f"{'' if self.spent_this_sample()[0] is not None else f', or {self.token_cap:,} tokens for unpriced models'})"
        )
