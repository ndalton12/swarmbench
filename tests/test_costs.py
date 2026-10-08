from pathlib import Path

import pytest
from inspect_ai.model import ModelCost, ModelUsage

from swarmbench import costs
from swarmbench.config import load_scenario
from tests.conftest import make_scenario

SONNET = "anthropic/claude-sonnet-5-5"


def test_prices_file_has_current_anthropic_models():
    prices = costs.load_prices(costs.REPO_PRICES)
    assert prices["anthropic/claude-opus-5-5"] == ModelCost(
        input=4, output=20, input_cache_write=5, input_cache_read=0.2
    )
    assert prices[SONNET].output == 10
    assert prices["anthropic/claude-haiku-4-5"].input == 1
    # Prices we could not verify are left out rather than guessed.
    assert not any(name.startswith("openai/") for name in prices)


def test_price_of():
    assert costs.price_of(SONNET).input == 2
    assert costs.price_of("mockllm/model") == costs.FREE
    # No known price: a deliberately high assumed price, never $0 and never "unknown".
    assert costs.known_price("openai/gpt-5.5") is None
    assert costs.price_of("openai/gpt-5.5") == costs.ASSUMED_PRICE
    assert costs.price_of("nobody/made-this-up") == costs.ASSUMED_PRICE
    assert costs.ASSUMED_PRICE.input == 10 and costs.ASSUMED_PRICE.output == 50
    assert costs.assumed_price_models([SONNET, "openai/gpt-5.5", "openai/gpt-5.5", "mockllm/model"]) == [
        "openai/gpt-5.5"
    ]


def test_assumed_price_warning_is_loud_and_specific():
    assert costs.assumed_price_warning([]) is None
    w = costs.assumed_price_warning(["openai/gpt-5.5"])
    assert w.startswith("WARNING") and "openai/gpt-5.5" in w and "$10" in w and "$50" in w


def test_inspect_prices_are_used_when_prices_yaml_has_none(monkeypatch):
    """A model Inspect learns the price of (e.g. after an upgrade) stops being assumed."""
    from inspect_ai.model import ModelCost, ModelInfo

    real = ModelCost(input=1, output=3, input_cache_write=1, input_cache_read=0.1)
    monkeypatch.setattr(costs, "get_model_info", lambda m: ModelInfo(model=m, cost=real))
    assert costs.price_of("openai/gpt-5.5") == real
    assert costs.assumed_price_models(["openai/gpt-5.5"]) == []


def test_prices_file_from_environment(tmp_path, monkeypatch):
    f = tmp_path / "p.yaml"
    f.write_text("openai/gpt-5.5: {input: 1, output: 2, input_cache_write: 1, input_cache_read: 0.1}\n")
    monkeypatch.setenv("SWARMBENCH_PRICES", str(f))
    assert costs.price_of("openai/gpt-5.5").output == 2
    assert costs.known_price(SONNET) is None


def test_estimate_uses_highest_rate_and_epochs(tmp_path):
    s = load_scenario(
        make_scenario(
            tmp_path, f"name: x\nswarm: {{agents: 4, model: {SONNET}, token_budget: 2M}}\nepochs: 3\n"
        )
    )
    e = costs.estimate_max_cost(s)
    # 2M tokens at Sonnet 5.5's highest rate ($10/M output) = $20 per epoch.
    assert e.swarm_per_epoch == pytest.approx(20)
    assert e.judge_per_epoch == pytest.approx(10)  # no max_cost: the judge's default $10 cap
    assert e.total == pytest.approx(90)
    assert not e.capped


def test_estimate_capped_by_max_cost_and_teams(tmp_path):
    s = load_scenario(
        make_scenario(
            tmp_path,
            f"name: x\nswarm: {{model: {SONNET}, token_budget: 1M}}\nmax_cost: 12\n"
            "teams: [{name: red}, {name: blue, model: anthropic/claude-opus-5-5}]\n",
        )
    )
    e = costs.estimate_max_cost(s)
    # Uncapped: red $10 + blue $20 = $30, so the $12 cap applies.
    assert e.capped and e.swarm_per_epoch == 12
    assert e.total == pytest.approx(12 + 3)
    assert len(e.lines) == 2


def test_estimate_uses_assumed_price_without_a_known_one(tmp_path):
    s = load_scenario(
        make_scenario(tmp_path, "name: x\nswarm: {model: openai/gpt-5.5, token_budget: 2M}\nmax_cost: 400\n")
    )
    e = costs.estimate_max_cost(s)
    # 2M tokens at the assumed $50/M output rate.
    assert e.uncapped_per_epoch == pytest.approx(100)
    assert e.total is not None and e.assumed_price_models == ["openai/gpt-5.5"]
    assert any("assumed price" in line for line in e.lines)


def test_judge_cap_rule(tmp_path):
    capped = load_scenario(make_scenario(tmp_path / "a", "name: a\nmax_cost: 40\n"))
    small = load_scenario(make_scenario(tmp_path / "b", "name: b\nmax_cost: 2\n"))
    open_ended = load_scenario(make_scenario(tmp_path / "c", "name: c\n"))
    assert costs.judge_cap(capped) == 10  # 25% of max_cost
    assert costs.judge_cap(small) == 1  # at least $1
    assert costs.judge_cap(open_ended) == 10  # no max_cost: $10
    # An explicit advanced.judge_max_cost wins.
    explicit = load_scenario(
        make_scenario(tmp_path / "d", "name: d\nmax_cost: 40\nadvanced: {judge_max_cost: 3.5}\n")
    )
    assert costs.judge_cap(explicit) == 3.5
    assert costs.reservation(explicit) == pytest.approx(40 + 3.5)


def test_thirty_million_token_default_is_capped_by_max_cost(tmp_path):
    s = load_scenario(
        make_scenario(tmp_path, f"name: x\nswarm: {{agents: 4, model: {SONNET}}}\nmax_cost: 40\n")
    )
    e = costs.estimate_max_cost(s)
    assert s.swarm.token_budget == 30_000_000
    assert e.capped and e.swarm_per_epoch == 40 and e.uncapped_per_epoch == pytest.approx(300)
    assert e.total == pytest.approx(50)


def test_eval_logs_cost_sums_every_epoch(tmp_path):
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ModelInfo, set_model_info

    # Price the mock model so the logged cost is visible: $1 per million output tokens.
    set_model_info(
        "mockllm/model",
        ModelInfo(cost=ModelCost(input=0, output=1e6, input_cache_write=0, input_cache_read=0)),
    )
    try:
        (log,) = eval(
            Task(dataset=[Sample(input="hi")], epochs=3),
            model="mockllm/model",
            display="none",
            log_dir=str(tmp_path),
        )
        summary = costs.eval_logs_cost([Path(log.location)])
        per_sample = [s.model_usage["mockllm/model"] for s in log.samples]
        assert summary.tokens == sum(u.total_tokens for u in per_sample)
        assert summary.usd == pytest.approx(sum(u.output_tokens for u in per_sample))
        assert len(per_sample) == 3
    finally:
        costs.model_cost_config()  # restore the mock model's $0 price
    assert costs.eval_logs_cost([tmp_path / "missing.eval"]) is None


def test_reservation(tmp_path):
    s = load_scenario(make_scenario(tmp_path, "name: x\nmax_cost: 20\nepochs: 2\n"))
    assert costs.reservation(s) == pytest.approx((20 + 5) * 2)  # judge cap: 25% of $20
    assert costs.reservation(s, judge_per_epoch=1) == pytest.approx(42)
    s2 = load_scenario(make_scenario(tmp_path / "b", "name: y\n"))
    with pytest.raises(ValueError, match="no max_cost"):
        costs.reservation(s2)


def test_usage_cost():
    usage = {
        SONNET: ModelUsage(input_tokens=1_000_000, output_tokens=100_000, total_tokens=1_100_000),
        "anthropic/claude-haiku-4-5": ModelUsage(output_tokens=10, total_tokens=10, total_cost=0.5),
    }
    s = costs.usage_cost(usage)
    assert s.by_model[SONNET] == pytest.approx(2 + 1)
    assert s.usd == pytest.approx(3.5)
    assert s.tokens == 1_100_010

    s = costs.usage_cost({"openai/gpt-5.5": ModelUsage(output_tokens=1_000, total_tokens=1_000)})
    assert s.usd == pytest.approx(0.05) and s.assumed_price_models == ["openai/gpt-5.5"]
    assert costs.summary_usd(s) == pytest.approx(0.05)


def test_model_cost_config_gives_unknown_run_models_the_assumed_price():
    """So Inspect can still enforce max_cost for a model with no known price."""
    from inspect_ai.model import get_model_info

    costs.model_cost_config(models=["nobody/made-this-up"])
    try:
        assert get_model_info("nobody/made-this-up").cost == costs.ASSUMED_PRICE
    finally:
        costs.model_cost_config()


def test_inspect_rejects_cost_limit_for_unpriced_mock_model(tmp_path):
    """Why model_cost_config registers the mock model: without it Inspect refuses to start."""
    from inspect_ai import Task, eval
    from inspect_ai._util.error import PrerequisiteError
    from inspect_ai.dataset import Sample
    from inspect_ai.model._model_info import clear_model_info_cache

    clear_model_info_cache()
    with pytest.raises(PrerequisiteError, match="mockllm/model"):
        eval(
            Task(dataset=[Sample(input="hi")]),
            model="mockllm/model",
            cost_limit=1.0,
            display="none",
            log_dir=str(tmp_path),
        )


def test_model_cost_config_lets_inspect_enforce_cost_limit_on_mock_model(tmp_path):
    """Inspect refuses cost_limit for an unpriced model; our config must cover mockllm."""
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample

    config = costs.model_cost_config()
    assert SONNET in config and "mockllm/model" not in config
    task = Task(dataset=[Sample(input="hi", target="x")])
    (log,) = eval(
        task,
        model="mockllm/model",
        model_cost_config=config,
        cost_limit=1.0,
        display="none",
        log_dir=str(tmp_path),
    )
    assert log.status == "success"
