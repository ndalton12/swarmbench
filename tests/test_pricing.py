"""OpenRouter's price list: reading it, matching our model names, the saved copy and refreshing it.
No network: the fetch is always a stand-in."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from swarmbench import costs, pricing

LISTING = {
    "data": [
        {
            "id": "anthropic/claude-opus-5.5",
            "pricing": {
                "prompt": "0.000004",
                "completion": "0.00002",
                "input_cache_read": "0.0000002",
                "input_cache_write": "0.000005",
            },
        },
        {"id": "anthropic/claude-opus-5.5:batch", "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
        {
            "id": "z-ai/glm-5.3-flash",
            "pricing": {
                "prompt": "0.0000000261",
                "completion": "0.0000009",
                "input_cache_read": "0.0000000108",
            },
        },
        {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
        {"id": "broken/model", "pricing": {}},
    ]
}


def test_the_list_is_read_in_dollars_per_million_without_variants_or_routers():
    models = pricing.parse_models(LISTING)
    assert set(models) == {"anthropic/claude-opus-5.5", "z-ai/glm-5.3-flash"}
    assert models["anthropic/claude-opus-5.5"] == {
        "input": 4.0,
        "output": 20.0,
        "input_cache_write": 5.0,
        "input_cache_read": 0.2,
    }
    glm = models["z-ai/glm-5.3-flash"]
    assert glm["input_cache_write"] == glm["input"] == 0.0261  # no cache-write price: as plain input


def test_our_names_match_openrouters_names():
    assert pricing.canonical("anthropic/claude-opus-5-5") == pricing.canonical("anthropic/claude-opus-5.5")
    assert pricing.canonical("openrouter/z-ai/glm-5.3-flash") == pricing.canonical("z-ai/glm-5.3-flash")
    assert pricing.canonical("openrouter/z-ai/glm-5.3-flash:nitro") == pricing.canonical("z-ai/glm-5.3-flash")
    # from the fixed snapshot every test reads
    assert costs.known_price("openrouter/z-ai/glm-5.3-flash").output == 0.9
    assert costs.price_source("openrouter/z-ai/glm-5.3-flash") == "OpenRouter's list price (2026-10-13)"
    assert costs.known_price("openai/gpt-5.5") is None  # not on the list: the loud assumed price


def test_refresh_fetches_only_when_old_and_keeps_the_list_when_it_fails(tmp_path, monkeypatch):
    monkeypatch.delenv(pricing.OFFLINE_ENV, raising=False)
    path = tmp_path / "prices.json"
    calls: list[int] = []

    def fetcher():
        calls.append(1)
        return LISTING

    first = pricing.refresh(fetcher=fetcher, path=path)
    assert first.status == "updated" and first.count == 2 and len(calls) == 1
    assert (
        pricing.refresh(fetcher=fetcher, path=path).status == "fresh" and len(calls) == 1
    )  # a week old at most

    data = json.loads(path.read_text())
    data["fetched"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    path.write_text(json.dumps(data))

    def broken():
        raise OSError("no network")

    failed = pricing.refresh(fetcher=broken, path=path)
    assert failed.status == "failed" and "no network" in failed.error and failed.count == 2
    assert "using the saved list from" in pricing.describe(failed)
    assert pricing.load(path).lookup("anthropic/claude-opus-5-5") is not None  # still there

    cheaper = {"data": [dict(LISTING["data"][0], pricing={"prompt": "0.000003", "completion": "0.00002"})]}
    again = pricing.refresh(force=True, fetcher=lambda: cheaper, path=path)
    changed = {
        m: (old["input"] if old else None, new["input"] if new else None) for m, old, new in again.changed
    }
    assert changed == {"anthropic/claude-opus-5.5": (4.0, 3.0), "z-ai/glm-5.3-flash": (0.0261, None)}


def test_offline_never_fetches(tmp_path):
    result = pricing.refresh(
        fetcher=lambda: (_ for _ in ()).throw(AssertionError("fetched")), path=tmp_path / "p.json"
    )
    assert result.status == "offline"  # the test setup turns fetching off


def test_inspect_is_given_the_list_price_for_a_run(monkeypatch):
    registered = costs.model_cost_config(models=["openrouter/z-ai/glm-5.3-flash", "openai/gpt-5.5"])
    from inspect_ai.model import get_model_info

    info = get_model_info("openrouter/z-ai/glm-5.3-flash")
    price = registered.get("openrouter/z-ai/glm-5.3-flash") or (info.cost if info else None)
    assert price is not None and price.output == 0.9


def test_a_list_that_cant_be_saved_keeps_the_old_one(tmp_path, monkeypatch):
    monkeypatch.delenv(pricing.OFFLINE_ENV, raising=False)
    path = tmp_path / "prices.json"
    assert pricing.refresh(fetcher=lambda: LISTING, path=path).status == "updated"

    def full_disk(*a, **k):
        raise OSError("No space left on device")

    monkeypatch.setattr(pricing, "_write_atomic", full_disk)
    result = pricing.refresh(force=True, fetcher=lambda: LISTING, path=path)
    assert result.status == "failed" and "couldn't save it" in result.error and result.count == 2
    assert pricing.load(path).lookup("anthropic/claude-opus-5-5") is not None
