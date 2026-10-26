"""Tests for the self-contradiction flagging step. Only Inspect's mock model is used: no paid calls."""

from __future__ import annotations

import asyncio
import json

import pandas as pd
from inspect_ai.model import ModelOutput, get_model

from swarmbench.studies.auditor import flags as fl
from swarmbench.studies.auditor import score as sc


def _request() -> sc.FlagRequest:
    return sc.FlagRequest(
        "test",
        "ch1",
        [
            {"step": 0, "command": "cat notes.txt", "predicted_output": "alpha  beta\ngamma"},
            {"step": 1, "command": "ls", "predicted_output": "notes.txt  run.sh"},
            {"step": 2, "command": "cat notes.txt", "predicted_output": "delta"},
        ],
    )


GOOD = {"step_a": 0, "step_b": 2, "quote_a": "alpha beta", "quote_b": "delta", "reason": "file changed"}


def test_request_never_shows_real_outputs():
    text = fl.request_text(_request())
    assert "=== Step 0 ===" in text and "$ cat notes.txt" in text and "delta" in text
    messages = fl.build_messages(_request())
    assert len(messages) == 2 and "JSON array" in messages[0].text


def test_parse_flags_keeps_only_checked_flags():
    bad_quote = {**GOOD, "quote_b": "epsilon"}
    wrong_order = {**GOOD, "step_a": 2, "step_b": 0}
    missing_step = {**GOOD, "step_b": 9}
    reply = "Here you go:\n" + json.dumps([GOOD, bad_quote, wrong_order, missing_step, {"step_a": "x"}])
    flags, problems = fl.parse_flags(reply, _request())
    assert [(f.step_a, f.step_b, f.quote_a) for f in flags] == [(0, 2, "alpha beta")]
    assert len(problems) == 4


def test_parse_flags_empty_and_unreadable():
    assert fl.parse_flags("[]", _request()) == ([], [])
    assert fl.parse_flags("no contradictions", _request())[1] == ["no JSON array in the reply"]


def _mock(*replies: str):
    return get_model(
        "mockllm/model", custom_outputs=[ModelOutput.from_content("mockllm/model", r) for r in replies]
    )


def test_flag_chains_with_the_mock_model(tmp_path):
    reqs = [_request(), sc.FlagRequest("test", "ch2", _request().steps)]
    records = asyncio.run(
        fl.flag_chains(reqs, model=_mock(json.dumps([GOOD]), "[]"), answers_dir=tmp_path, chains_at_once=1)
    )
    assert [len(r["flags"]) for r in records] == [1, 0]
    assert all(r["error"] is None and r["request_hash"] for r in records)
    assert not (tmp_path / "spend_ledger.jsonl").exists()  # not live: nothing charged


def test_live_path_reserves_charges_and_refuses(tmp_path):
    """The live path, still with the mock model passed in: a call that fits is charged to the ledger;
    with no room left under the cap, the budget guard refuses before any call."""
    records = asyncio.run(
        fl.flag_chains([_request()], model=_mock("[]"), live=True, cap_usd=5.0, answers_dir=tmp_path)
    )
    assert records[0]["error"] is None
    ledger = [json.loads(x) for x in (tmp_path / "spend_ledger.jsonl").read_text().splitlines()]
    assert ledger[0]["batch"] == "test-flags" and ledger[0]["kind"] == "contradiction flags"
    assert (tmp_path / ".rm-protect").exists()
    refused = asyncio.run(
        fl.flag_chains([_request()], model=_mock("[]"), live=True, cap_usd=1e-7, answers_dir=tmp_path / "fresh")
    )
    assert refused[0]["error"].startswith("refused by the budget guard")


def test_live_needs_a_real_model_name(tmp_path):
    asyncio.run(
        fl.flag_chains(
            [_request()], model=_mock("[]"), model_name="mockllm/model", live=True, answers_dir=tmp_path
        )
    )
    assert not (tmp_path / "spend_ledger.jsonl").exists()


def test_confirmation_table_combines_rules_and_model():
    scores = pd.DataFrame(
        {
            "split": "test",
            "situation": "chain",
            "variant": "main",
            "chain_id": "ch1",
            "step": [0, 1],
            "key": ["k0", "k1"],
            "command": ["ls /srv", "ls /srv"],
            "output": ["a", "a"],
            "output_status": "complete",
            "predicted_output": ["a", "b"],
            "parse_ok": True,
        }
    )
    rec = {
        "flags": [
            {
                "split": "test",
                "chain_id": "ch1",
                "step_a": 0,
                "step_b": 1,
                "quote_a": "a",
                "quote_b": "b",
                "reason": "changed",
            }
        ]
    }
    table = fl.confirmation_table(scores, [rec])
    assert sorted(table["source"]) == ["model", "rule: same_real_output"]
    assert (table["confirmed"] == "").all()
