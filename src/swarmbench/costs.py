"""Model prices and cost estimates.

Prices live in ``prices.yaml`` (Inspect's model_cost_config format: dollars per million
tokens for input, output, cache writes and cache reads). The file is looked up in this order:
the ``SWARMBENCH_PRICES`` environment variable, ``./prices.yaml`` in the current folder, then
the copy at the repository root.

A model's price comes from prices.yaml, else from Inspect's own model database (which will
cover more models as Inspect is updated), else it is assumed to be ``ASSUMED_PRICE``: a
deliberately high rate, so caps and estimates err towards spending less, never more. Costs
worked out at the assumed price are flagged (``assumed_price_models``) and every launch warns
loudly about them. The mock model (``mockllm/...``) costs nothing.
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

# Dollars per million tokens for a model with no known price. Deliberately high (above every
# listed model's input and output rates), so a cap or estimate based on it is conservative.
ASSUMED_PRICE = ModelCost(input=10.0, output=50.0, input_cache_write=12.5, input_cache_read=1.0)

# The judge stops itself at a dollar cap per epoch: ``advanced.judge_max_cost`` if set, else
# this share of the scenario's max_cost (at least JUDGE_MIN_USD), else JUDGE_DEFAULT_USD.
# The same rule is applied by the judge (swarmbench.judge); keep the two in step.
JUDGE_SHARE = 0.25
JUDGE_MIN_USD = 2.5
"""The two-pass judge keeps back about $1 for its final review (its answer, one repair round and
the summary, reserved at their full output allowance) and spends about $1 more reading even a
small run with Opus 5.5, so a smaller cap would leave it unable to finish."""
JUDGE_DEFAULT_USD = 10.0


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


def known_price(model: str, prices: dict[str, ModelCost] | None = None) -> ModelCost | None:
    """A model's real price, or None if neither prices.yaml nor Inspect knows it.

    Looks in prices.yaml first, then in Inspect's own model database.
    """
    if is_mock(model):
        return FREE
    prices = load_prices() if prices is None else prices
    if model in prices:
        return prices[model]
    try:
        info = get_model_info(model)
    except Exception:
        return None
    return info.cost if info and info.cost else None


def price_of(model: str, prices: dict[str, ModelCost] | None = None) -> ModelCost:
    """A model's price: its known price, else ``ASSUMED_PRICE``."""
    return known_price(model, prices) or ASSUMED_PRICE


def assumed_price_models(models: list[str], prices: dict[str, ModelCost] | None = None) -> list[str]:
    """The models in ``models`` priced at ``ASSUMED_PRICE``, in order and without repeats."""
    prices = load_prices() if prices is None else prices
    out: list[str] = []
    for m in models:
        if m and m not in out and known_price(m, prices) is None:
            out.append(m)
    return out


def assumed_price_warning(models: list[str]) -> str | None:
    """A loud, plain warning about models priced at ``ASSUMED_PRICE``, or None if there are none."""
    if not models:
        return None
    p = ASSUMED_PRICE
    return (
        f"WARNING: no known price for {', '.join(models)}. Assuming ${p.input:g} per million input tokens, "
        f"${p.output:g} per million output tokens (cache writes ${p.input_cache_write:g}, cache reads "
        f"${p.input_cache_read:g}). Costs, caps and estimates for these models are guesses: a cap may stop "
        "a run early, and real spending may differ. Check the provider's bill, or add the real price "
        "to prices.yaml."
    )


def model_cost_config(
    path: str | Path | None = None, models: list[str] | None = None
) -> dict[str, ModelCost]:
    """Prices to pass to ``inspect_ai.eval(model_cost_config=...)``.

    Every model in ``models`` without a known price is given ``ASSUMED_PRICE``, so Inspect
    can still enforce a cost limit. Inspect's ``set_model_cost`` refuses models it has never
    heard of, such as the mock model. Those are registered here directly with
    ``set_model_info`` and left out of the returned dict, so a dry run with a cost limit works too.
    """
    prices = load_prices(path)
    prices.setdefault("mockllm/model", FREE)
    for m in assumed_price_models(list(models or []), prices):
        prices[m] = ASSUMED_PRICE
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

    Uses the cost Inspect already computed when there is one. Models without a known price
    are costed at ``ASSUMED_PRICE`` and listed in ``assumed_price_models``.
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
            usd = _cost_of_usage(usage, price_of(model, prices))
        if known_price(model, prices) is None:
            summary.assumed_price_models.append(model)
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
    max_cost: float | None = None
    """The scenario's dollar cap per epoch, if any."""
    uncapped_per_epoch: float | None = None
    """What the token budgets alone would allow per epoch (None when a model has no price)."""
    unpriced_models: list[str] = field(default_factory=list)
    assumed_price_models: list[str] = field(default_factory=list)
    """Models costed at ``ASSUMED_PRICE`` because their real price isn't known."""
    lines: list[str] = field(default_factory=list)
    """A short plain-language breakdown, one line per team."""
    judge_models: list[str] = field(default_factory=list)
    """The judge's model, then its fallback reader if any (the cap is spent at their prices)."""

    @property
    def total(self) -> float | None:
        if self.swarm_per_epoch is None or self.judge_per_epoch is None:
            return None
        return (self.swarm_per_epoch + self.judge_per_epoch) * self.epochs


def judge_allowance(swarm_per_epoch: float) -> float:
    """Dollars set aside for judging one epoch when the scenario sets no judge cap."""
    return max(JUDGE_MIN_USD, JUDGE_SHARE * swarm_per_epoch)


def judge_roles(scenario: Scenario) -> dict[str, str]:
    """The judge's models for this scenario, by role:

    - ``judge``: makes every judgment. ``advanced.judge_model``, else the judge's default.
    - ``fallback`` (if the judge has one): only reads quiet stretches of a transcript when the
      judge's cost cap would otherwise be exceeded. ``advanced.judge_fallback_model``, else
      the judge's default fallback.
    """
    from swarmbench import judge  # imported here: the judge imports this module

    main = (
        scenario.advanced.judge_model
        or getattr(judge, "DEFAULT_JUDGE_MODEL", None)
        or (getattr(judge, "DEFAULT_JUDGE_MODELS", None) or [None])[0]
        or getattr(judge, "DEFAULT_SUMMARIZER_MODEL", None)
    )
    fallback = getattr(scenario.advanced, "judge_fallback_model", None) or getattr(
        judge, "DEFAULT_JUDGE_FALLBACK_MODEL", None
    )
    roles = {"judge": main} if main else {}
    if fallback and fallback != main:
        roles["fallback"] = fallback
    return roles


def judge_models(scenario: Scenario) -> list[str]:
    """Every model the judge may spend its cap on: the judge, then its fallback."""
    return list(judge_roles(scenario).values())


def judge_overlap(scenario: Scenario) -> dict[str, str]:
    """The judge roles whose model is also an agent model in this scenario (role -> model)."""
    agents = {t.model for t in scenario.resolved_teams()}
    return {role: m for role, m in judge_roles(scenario).items() if m in agents}


def judge_cap(scenario: Scenario) -> float:
    """The judge's dollar cap for one epoch, which the judge enforces itself.

    ``advanced.judge_max_cost`` if set; otherwise 25% of max_cost (at least $2.50); otherwise $10.
    The judge may go over by at most one model call already under way.
    """
    explicit = getattr(scenario.advanced, "judge_max_cost", None)
    if explicit is not None:
        return explicit
    if scenario.max_cost is not None:
        return judge_allowance(scenario.max_cost)
    return JUDGE_DEFAULT_USD


def estimate_max_cost(scenario: Scenario, prices: dict[str, ModelCost] | None = None) -> CostEstimate:
    """Worst-case cost of running a scenario, before it starts.

    Formula, per epoch:

    - each team: ``token_budget / 1e6 * highest rate`` for its model, where the highest rate
      is the largest of the input, output, cache-write and cache-read prices (in practice the
      output price). The token budget counts every token, so this is an upper bound unless
      the last model call of an agent overshoots its budget.
    - swarm: the sum over teams, then capped at ``max_cost`` when the scenario has one
      (Inspect stops the sample there, give or take one model call).
    - judge: the judge's own cap per epoch (``judge_cap``): ``advanced.judge_max_cost``, or
      25% of max_cost (at least $2.50), or $10.

    Models without a known price are costed at ``ASSUMED_PRICE`` and listed in
    ``assumed_price_models``.

    Total = (swarm + judge) * epochs. Calls by the optional monitor model are not included.
    """
    prices = load_prices() if prices is None else prices
    swarm: float | None = 0.0
    lines: list[str] = []
    for team in scenario.resolved_teams():
        price = price_of(team.model, prices)
        label = f"{team.name}: {team.agents} x {team.model}, {team.token_budget:,} tokens"
        if known_price(team.model, prices) is None:
            label += " (assumed price)"
        rate = max(price.input, price.output, price.input_cache_write, price.input_cache_read)
        team_cost = team.token_budget / 1_000_000 * rate
        lines.append(f"{label}: up to ${team_cost:,.2f}")
        if swarm is not None:
            swarm += team_cost

    uncapped = swarm
    capped = False
    if scenario.max_cost is not None and (swarm is None or swarm > scenario.max_cost):
        swarm = scenario.max_cost
        capped = True
    judges = judge_models(scenario)
    judge: float | None = judge_cap(scenario)
    assumed = assumed_price_models([t.model for t in scenario.resolved_teams()] + judges, prices)
    return CostEstimate(
        swarm_per_epoch=swarm,
        judge_per_epoch=judge,
        epochs=scenario.epochs,
        capped=capped,
        max_cost=scenario.max_cost,
        uncapped_per_epoch=uncapped,
        assumed_price_models=assumed,
        lines=lines,
        judge_models=judges,
    )


def reservation(scenario: Scenario, judge_per_epoch: float | None = None) -> float:
    """What a run reserves from an experiment's budget: its cap times epochs plus the judge.

    The scenario must have ``max_cost``; without it there is no bound to reserve.
    """
    if scenario.max_cost is None:
        raise ValueError(f"scenario {scenario.name!r} has no max_cost, so its cost can't be reserved")
    judge = judge_cap(scenario) if judge_per_epoch is None else judge_per_epoch
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


def eval_logs_cost(paths: list[Path], prices: dict[str, ModelCost] | None = None) -> CostSummary | None:
    """What every sample in these Inspect logs spent, from each sample's own model usage.

    Used to settle a run's final swarm cost across all epochs. None if no log could be read.
    """
    from inspect_ai.log import read_eval_log_sample_summaries

    usage: dict[str, ModelUsage] = {}
    read_any = False
    for path in paths:
        try:
            summaries = read_eval_log_sample_summaries(str(path))
        except Exception:
            continue
        read_any = True
        for sample in summaries:
            for model, u in sample.model_usage.items():
                usage[model] = usage[model] + u if model in usage else u
    return usage_cost(usage, prices) if read_any else None
