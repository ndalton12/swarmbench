"""Model prices and cost estimates.

Prices live in ``prices.yaml`` (Inspect's model_cost_config format: dollars per million
tokens for input, output, cache writes and cache reads). The file is looked up in this order:
the ``SWARMBENCH_PRICES`` environment variable, ``./prices.yaml`` in the current folder, then
the copy at the repository root.

A model without a price is never treated as free: its cost is reported as unknown (None).
The mock model (``mockllm/...``) is the one exception; it costs nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from inspect_ai.model import ModelCost, ModelInfo, ModelUsage, get_model_info, set_model_info

from swarmbench.config import Scenario
from swarmbench.types import CostSummary

REPO_PRICES = Path(__file__).resolve().parents[2] / "prices.yaml"

FREE = ModelCost(input=0, output=0, input_cache_write=0, input_cache_read=0)

# The judge is not covered by Inspect's cost_limit, so runs reserve an allowance for it:
# this share of the swarm's worst case per epoch, and at least JUDGE_MIN_USD.
JUDGE_SHARE = 0.25
JUDGE_MIN_USD = 1.0


def prices_path() -> Path:
    env = os.environ.get("SWARMBENCH_PRICES")
    if env:
        return Path(env)
    local = Path("prices.yaml")
    return local if local.exists() else REPO_PRICES


def load_prices(path: str | Path | None = None) -> dict[str, ModelCost]:
    """Read a prices file. A missing file means no prices."""
    file = Path(path) if path else prices_path()
    if not file.exists():
        return {}
    data = yaml.safe_load(file.read_text()) or {}
    return {name: ModelCost(**cost) for name, cost in data.items()}


def is_mock(model: str) -> bool:
    return model.startswith("mockllm/")


def price_of(model: str, prices: dict[str, ModelCost] | None = None) -> ModelCost | None:
    """The price of a model, or None if it has no price.

    Looks in prices.yaml first, then in Inspect's own model database.
    """
    if is_mock(model):
        return FREE
    prices = load_prices() if prices is None else prices
    if model in prices:
        return prices[model]
    try:
        info = get_model_info(model)
    except Exception:  # noqa: BLE001 - an unknown model just has no price
        return None
    return info.cost if info else None


def unpriced(models: list[str], prices: dict[str, ModelCost] | None = None) -> list[str]:
    """The models in ``models`` that have no price, in order and without repeats."""
    prices = load_prices() if prices is None else prices
    out: list[str] = []
    for m in models:
        if m not in out and price_of(m, prices) is None:
            out.append(m)
    return out


def model_cost_config(path: str | Path | None = None) -> dict[str, ModelCost]:
    """Prices to pass to ``inspect_ai.eval(model_cost_config=...)``.

    Inspect's ``set_model_cost`` refuses models it has never heard of, such as the mock
    model. Those are registered here directly with ``set_model_info`` and left out of the
    returned dict, so a dry run with a cost limit works too.
    """
    prices = load_prices(path)
    prices.setdefault("mockllm/model", FREE)
    known: dict[str, ModelCost] = {}
    for name, cost in prices.items():
        if not is_mock(name) and get_model_info(name) is not None:
            known[name] = cost
        else:
            set_model_info(name, ModelInfo(model=name, cost=cost))
    return known


def _cost_of_usage(usage: ModelUsage, price: ModelCost) -> float:
    from inspect_ai.model._model import compute_model_cost

    return compute_model_cost(price, usage)


def usage_cost(model_usage: dict[str, ModelUsage], prices: dict[str, ModelCost] | None = None) -> CostSummary:
    """Total tokens and dollars for Inspect's per-model usage (e.g. ``EvalSample.model_usage``).

    Uses the cost Inspect already computed when there is one. If any model has no price,
    ``usd`` is None and the model is listed in ``unpriced_models``.
    """
    prices = load_prices() if prices is None else prices
    summary = CostSummary()
    total: float | None = 0.0
    for model, usage in model_usage.items():
        cache = (usage.input_tokens_cache_read or 0) + (usage.input_tokens_cache_write or 0)
        summary.tokens += usage.total_tokens
        summary.input_tokens += usage.input_tokens + cache
        summary.output_tokens += usage.output_tokens
        usd = usage.total_cost
        if usd is None:
            price = price_of(model, prices)
            usd = _cost_of_usage(usage, price) if price is not None else None
        summary.by_model[model] = usd
        if usd is None:
            summary.unpriced_models.append(model)
            total = None
        elif total is not None:
            total += usd
    summary.usd = total
    return summary


@dataclass
class CostEstimate:
    """Worst-case dollars for one run. Any field is None when a model has no price."""

    swarm_per_epoch: float | None
    judge_per_epoch: float | None
    epochs: int
    capped: bool
    """True when the scenario's max_cost, not the token budgets, sets the swarm figure."""
    unpriced_models: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    """A short plain-language breakdown, one line per team."""

    @property
    def total(self) -> float | None:
        if self.swarm_per_epoch is None or self.judge_per_epoch is None:
            return None
        return (self.swarm_per_epoch + self.judge_per_epoch) * self.epochs


def judge_allowance(swarm_per_epoch: float) -> float:
    """Dollars set aside for judging one epoch."""
    return max(JUDGE_MIN_USD, JUDGE_SHARE * swarm_per_epoch)


def estimate_max_cost(scenario: Scenario, prices: dict[str, ModelCost] | None = None) -> CostEstimate:
    """Worst-case cost of running a scenario, before it starts.

    Formula, per epoch:

    - each team: ``token_budget / 1e6 * highest rate`` for its model, where the highest rate
      is the largest of the input, output, cache-write and cache-read prices (in practice the
      output price). The token budget counts every token, so this is an upper bound unless
      the last model call of an agent overshoots its budget.
    - swarm: the sum over teams, then capped at ``max_cost`` when the scenario has one
      (Inspect stops the sample there, give or take one model call).
    - judge: ``max(JUDGE_MIN_USD, JUDGE_SHARE * swarm)``. The judge has no hard cap; this is
      an allowance, not a bound.

    Total = (swarm + judge) * epochs. Calls by the optional monitor model are not included.
    """
    prices = load_prices() if prices is None else prices
    swarm: float | None = 0.0
    lines: list[str] = []
    missing: list[str] = []
    for team in scenario.resolved_teams():
        price = price_of(team.model, prices)
        label = f"{team.name}: {team.agents} x {team.model}, {team.token_budget:,} tokens"
        if price is None:
            missing.append(team.model)
            swarm = None
            lines.append(f"{label}: no price")
            continue
        rate = max(price.input, price.output, price.input_cache_write, price.input_cache_read)
        team_cost = team.token_budget / 1_000_000 * rate
        lines.append(f"{label}: up to ${team_cost:,.2f}")
        if swarm is not None:
            swarm += team_cost

    capped = False
    if scenario.max_cost is not None and (swarm is None or swarm > scenario.max_cost):
        swarm = scenario.max_cost
        capped = True
    judge = judge_allowance(swarm) if swarm is not None else None
    return CostEstimate(
        swarm_per_epoch=swarm,
        judge_per_epoch=judge,
        epochs=scenario.epochs,
        capped=capped,
        unpriced_models=missing,
        lines=lines,
    )


def reservation(scenario: Scenario, judge_per_epoch: float | None = None) -> float:
    """What a run reserves from an experiment's budget: its cap times epochs plus the judge.

    The scenario must have ``max_cost``; without it there is no bound to reserve.
    """
    if scenario.max_cost is None:
        raise ValueError(f"scenario {scenario.name!r} has no max_cost, so its cost can't be reserved")
    judge = judge_allowance(scenario.max_cost) if judge_per_epoch is None else judge_per_epoch
    return (scenario.max_cost + judge) * scenario.epochs


def format_usd(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"${value:,.2f}"


def summary_usd(*summaries: Any) -> float | None:
    """Add up CostSummary dollars; None if any of them is unknown."""
    total = 0.0
    for s in summaries:
        if s is None:
            continue
        if s.usd is None or s.unpriced_models:
            return None
        total += s.usd
    return total
