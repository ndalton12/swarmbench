"""A hard spending cap for the judge.

The cap is per sample (epoch): ``advanced.judge_max_cost`` dollars, or, when
that isn't set, ``costs.judge_allowance(max_cost)`` for a scenario with a
``max_cost`` and $10 otherwise. It is checked before every judge model call, so
spend can exceed it by at most the one call already in flight. When a model
has no price, a token cap stands in for the dollar cap.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

from swarmbench.types import CostSummary

DEFAULT_CAP_NO_MAX_COST = 10.0
TOKEN_CAP_WHEN_UNPRICED = 2_000_000
JUDGE_MAX_OUTPUT_TOKENS = 2_000
JUDGE_MAX_RETRIES = 3
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


@dataclass
class JudgeBudget:
    cap_usd: float
    token_cap: int = TOKEN_CAP_WHEN_UNPRICED
    spent_fn: Any = None
    """Returns the CostSummary spent so far (tests inject a fake)."""
    hit: bool = False
    _base: CostSummary = field(default_factory=lambda: CostSummary(tokens=0, usd=0.0))

    def spent_total(self) -> CostSummary:
        return self.spent_fn() if self.spent_fn else cost_of(usage_so_far())

    def start_sample(self) -> None:
        """The cap is per sample: measure from here."""
        self._base = self.spent_total()
        self.hit = False

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
