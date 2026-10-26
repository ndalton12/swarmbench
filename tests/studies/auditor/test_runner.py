"""The runner, end to end with Inspect's mock model only (never a real model)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from swarmbench.studies.auditor import cases as C
from swarmbench.studies.auditor import prompts as P
from swarmbench.studies.auditor import runner as R
from tests.studies.auditor.runner_fixtures import make_commands, make_run_dir

SIZES = C.DrawSizes(one_step_matter=8, one_step_other=2, long_history=2, repeats=2, chains=3, chain_real_past=3,
                    shared=5, shared_no_record=2, queue_moments=1, practice_one_step=3, practice_one_step_other=1,
                    practice_chains=1, practice_shared=1)


@pytest.fixture
def world(tmp_path):
    commands = C.normalise_commands(make_commands())
    draw = C.draw_cases(commands, C.stub_labels(commands), seed=5, sizes=SIZES)
    data = tmp_path / "data"
    C.save(draw, data)
    runs = tmp_path / "runs"
    for run_id in commands["run_id"].unique():
        make_run_dir(runs, run_id)
    cases, queue = C.load_cases(data)
    return commands, cases, queue, data, runs


def settings(data: Path, runs: Path, **kw) -> R.Settings:
    base = {"batch": "t", "dry_run": True, "data_dir": data, "runs_dir": runs, "quiet": True, "mock_style": "oracle"}
    return R.Settings(**{**base, **kw})


def lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


async def test_dry_run_answers_every_ask_and_prices_it(world):
    commands, cases, queue, data, runs = world
    run = R.AuditorRun(settings(data, runs), cases, queue, commands)
    summary = await run.run()
    answers = lines(data / "answers" / "t.jsonl")
    test_cases = cases[cases.split == "test"]
    assert {a["case_id"] for a in answers} == set(test_cases["case_id"])
    assert all(a["parse_ok"] and a["error"] is None for a in answers)
    # the oracle mock repeats the real output, so the reading-back is exact
    by_key = commands.set_index("key")
    a = next(x for x in answers if x["situation"] == "one_step")
    assert a["predicted_output"] == by_key.loc[a["key"], "output"]
    assert summary["spent_usd"] > 0 and summary["priced_as"] == R.DEFAULT_MODEL
    q = lines(data / "answers" / "t_queue.jsonl")
    assert len(q) == len(queue) and all(x["parse_ok"] for x in q)
    reqs = lines(data / "answers" / "t_requests.jsonl")
    assert len(reqs) == len(answers) + len(q)
    assert {x["request_hash"] for x in answers} <= {r["request_hash"] for r in reqs}
    # the agreed fields for aud-analysis are all there
    need = {"case_id", "key", "situation", "variant", "chain_id", "step", "instructions_version", "model", "seed",
            "predicted_output", "predicted_exit_code", "predicted_seconds", "predicted_low_s", "predicted_high_s",
            "predicted_never", "will_wait", "parse_ok", "raw", "error", "usage"}
    assert need <= set(answers[0])


async def test_chains_feed_the_auditors_own_answers_forward_and_read_the_cache(world):
    commands, cases, queue, data, runs = world
    run = R.AuditorRun(settings(data, runs, mock_style="noisy"), cases, queue, commands)
    await run.run()
    answers = {a["case_id"]: a for a in lines(data / "answers" / "t.jsonl")}
    reqs = {r["case_id"]: r for r in lines(data / "answers" / "t_requests.jsonl")}
    chain = cases[(cases.situation == "chain") & (cases.variant == "main") & (cases.split == "test")]
    cid = chain.chain_id.iloc[0]
    steps = chain[chain.chain_id == cid].sort_values("step")
    s3 = reqs[steps.case_id.iloc[3]]["messages"]
    assistant = [m["text"] for m in s3 if m["role"] == "assistant"]
    assert assistant == [answers[c]["raw"].strip() for c in steps.case_id.iloc[:3]]
    # later chain steps mostly read from the cache rather than paying full price
    later = [answers[c]["usage"] for c in steps.case_id.iloc[1:]]
    assert all(u.get("input_tokens_cache_read", 0) > u.get("input_tokens", 0) for u in later)
    # and within a run, every request after the first reads the fixed part back
    one = [a for a in answers.values() if a["situation"] == "one_step"]
    assert sum(1 for a in one if a["usage"].get("input_tokens_cache_read")) >= len(one) - 3


async def test_the_cap_stops_spending(world):
    commands, cases, queue, data, runs = world
    run = R.AuditorRun(settings(data, runs, cap_usd=0.05, groups_at_once=1, calls_per_group=1), cases, queue, commands)
    summary = await run.run()
    assert summary["cap_reached"]
    assert summary["spent_usd"] <= 0.05
    answers = lines(data / "answers" / "t.jsonl")
    assert any(a["error"] and "cap" in a["error"] for a in answers)
    assert len(answers) + len(lines(data / "answers" / "t_queue.jsonl")) == summary["asks"]  # all recorded


async def test_replay_reproduces_the_batch_without_a_model(world):
    commands, cases, queue, data, runs = world
    first = await R.AuditorRun(settings(data, runs, mock_style="noisy"), cases, queue, commands).run()
    s = settings(data, runs, batch="t-replay", dry_run=False, replay="t")
    again = await R.AuditorRun(s, cases, queue, commands).run()
    assert again["replay_misses"] == [] and again["errors"] == 0 and again["spent_usd"] == 0
    a = {x["case_id"]: x for x in lines(data / "answers" / "t.jsonl")}
    b = {x["case_id"]: x for x in lines(data / "answers" / "t-replay.jsonl")}
    assert a.keys() == b.keys()
    for k in a:
        assert (a[k]["raw"], a[k]["request_hash"], a[k]["predicted_seconds"]) == \
               (b[k]["raw"], b[k]["request_hash"], b[k]["predicted_seconds"])
    assert first["asks"] == again["asks"]


async def test_practice_runs_both_instruction_versions(world):
    commands, cases, queue, data, runs = world
    s = settings(data, runs, split="practice", versions=["a", "b"])
    await R.AuditorRun(s, cases, queue, commands).run()
    answers = lines(data / "answers" / "t.jsonl")
    practice = cases[cases.split == "practice"]
    assert len(answers) == 2 * len(practice)
    assert {a["instructions_version"] for a in answers} == {"a", "b"}
    assert not lines(data / "answers" / "t_queue.jsonl")  # queue moments are test-only


def test_a_real_model_needs_live(world):
    commands, cases, queue, data, runs = world
    with pytest.raises(SystemExit):
        R.AuditorRun(settings(data, runs, dry_run=False, model="anthropic/claude-opus-5-5"), cases, queue, commands)
    assert R.main(["--data-dir", str(data), "--model", "anthropic/claude-opus-5-5"]) == 2


def test_worst_case_is_never_below_the_real_price():
    from inspect_ai.model import GenerateConfig

    from swarmbench.costs import price_of

    est = R.worst_case(R.DEFAULT_MODEL)
    msgs = P.to_messages(P.Request(system="x" * 30_000, turns=[("user", "y" * 10_000)]))
    usd, _tokens = est(None, msgs, GenerateConfig(max_tokens=4000))
    p = price_of(R.DEFAULT_MODEL)
    assert usd >= (40_000 / 4 * p.input + 4000 * p.output) / 1e6


def test_cache_simulator():
    sim = R.CacheSimulator()
    req = P.Request(system="S" * 4000, turns=[("user", "U" * 2000)])
    msgs = P.to_messages(req)
    u1 = sim.usage(msgs, 10)
    assert u1.input_tokens_cache_write > 0 and not u1.input_tokens_cache_read
    u2 = sim.usage(P.to_messages(P.Request(system="S" * 4000, turns=[("user", "V" * 2000)])), 10)
    assert u2.input_tokens_cache_read == u1.input_tokens_cache_write and not u2.input_tokens_cache_write
    small = sim.usage(P.to_messages(P.Request(system="tiny", turns=[("user", "q")])), 10)
    assert not small.input_tokens_cache_write  # below the minimum cacheable size


def test_projection_table_lists_every_plan_item():
    items = {"several steps: chains": {"calls": 10, "usd": 0.2, "input": 0, "cache_read": 0, "cache_write": 0,
                                       "output": 0}}
    text = R.projection_table(items)
    for name in R.PLAN_COSTS:
        assert name in text
    assert "5.12" in text  # 256 chain steps at $0.02


def test_prior_spending_counts_only_real_batches(tmp_path):
    d = tmp_path / "answers"
    d.mkdir()
    (d / "a_summary.json").write_text(json.dumps({"batch": "a", "dry_run": False, "model": "anthropic/x", "spent_usd": 3}))
    (d / "b_summary.json").write_text(json.dumps({"batch": "b", "dry_run": True, "model": "mockllm/model", "spent_usd": 9}))
    (d / "c_summary.json").write_text(json.dumps({"batch": "c", "dry_run": False, "model": "replay of a", "spent_usd": 0}))
    assert R.prior_spending(d, "z") == 3 and R.prior_spending(d, "a") == 0


def test_item_of_maps_to_the_plan():
    assert R.item_of({"split": "practice", "situation": "chain", "variant": "main"}).startswith("practice")
    assert R.item_of({"split": "test", "situation": "shared", "variant": "no_record"}) in R.PLAN_COSTS
    assert R.item_of({"split": "test", "situation": "queue", "variant": "main"}) in R.PLAN_COSTS


def test_cli_dry_run(world, capsys, monkeypatch):
    commands, _cases, _queue, data, runs = world
    monkeypatch.setattr(R, "load_commands", lambda: commands)
    monkeypatch.setattr(R, "RUNS_DIR", runs)
    assert R.main(["--dry-run", "--split", "all", "--data-dir", str(data), "--limit", "6"]) == 0
    out = capsys.readouterr().out
    assert "projected cost" in out and "total" in out
    assert (data / "answers" / "practice-dryrun.jsonl").exists() and (data / "answers" / "test-dryrun.jsonl").exists()
    assert isinstance(pd.read_json(data / "answers" / "test-dryrun.jsonl", lines=True), pd.DataFrame)
