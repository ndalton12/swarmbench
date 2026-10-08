"""Regression tests for Codex's review of judge stage 3, one per issue, following its scenarios.
Mock and replay only."""

from __future__ import annotations

import json
import shutil
from typing import Any

import anyio
import pytest
from inspect_ai.model import ModelOutput, get_model

import swarmbench.judge as J
from swarmbench.judge import budget as B
from swarmbench.judge import judge_run
from swarmbench.judge import projection as P
from swarmbench.judge import two_pass as TP
from swarmbench.paths import RunDir
from tests.fixtures import build_mock_log
from tests.test_judge_two_pass import _default, _kind

OPUS, SONNET = "anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5"


def _answer(decide):
    def outputs(input, tools, tool_choice, config):
        out = decide(list(input))
        return out if isinstance(out, ModelOutput) else ModelOutput.from_content("mockllm/model", out)

    return get_model("mockllm/model", custom_outputs=outputs)


def _judge(rd: RunDir, main: Any, fallback: Any = None, **kwargs: Any) -> Any:
    async def go():
        original_models, original_fallback = J._resolve_models, J._resolve_fallback
        J._resolve_models = lambda m, judge_model=None: J._Models(main, main, main, main)
        J._resolve_fallback = lambda m, name: fallback if fallback is not None else main
        try:
            return await J._judge_async(rd, None, engine="two-pass", **kwargs)
        finally:
            J._resolve_models, J._resolve_fallback = original_models, original_fallback

    return anyio.run(go)


def _all_to_fallback(monkeypatch) -> None:
    """Force the cost plan to send every part to the fallback reader."""
    real = TP.project

    def project(**kwargs):
        p = real(**kwargs)
        p.fallback_chunks = [c.id for c in kwargs["chunks"]]
        return p

    monkeypatch.setattr(TP, "project", project)


# --- 2 (first): the budget guard can't be bypassed ---------------------------------------------------------


@pytest.mark.parametrize("samples", [1, 2])
def test_the_cap_holds_with_one_model_as_main_and_fallback(tmp_path, monkeypatch, samples):
    rd = RunDir.create("impossible-math", base=tmp_path)
    path = build_mock_log(rd.logs)
    for i in range(1, samples):  # a second sample: the same fallback reader is used again
        shutil.copy(path, rd.logs / f"copy{i}-{path.name}")
    _all_to_fallback(monkeypatch)
    calls: list[str] = []

    def decide(messages):
        calls.append(_kind(messages))
        return _default(messages)

    model = _answer(decide)  # the very same object as main model and as fallback
    # every call reserves its cost; at this estimate none fits under the cap
    monkeypatch.setattr(B, "estimate_call", lambda model, input, config=None: (None, 10**9))
    reports = _judge(rd, model, model)
    assert len(reports) == samples
    assert calls == []  # no call slipped past the guard, for either reader, in any sample
    for r in reports:
        assert r.headline.startswith("Not fully assessed") and "budget ran out" in r.coverage


@pytest.mark.parametrize("samples", [1, 2])
def test_every_call_is_reserved_first(tmp_path, monkeypatch, samples):
    rd = RunDir.create("impossible-math", base=tmp_path)
    path = build_mock_log(rd.logs)
    for i in range(1, samples):
        shutil.copy(path, rd.logs / f"copy{i}-{path.name}")
    _all_to_fallback(monkeypatch)
    calls, reservations = [], []
    real_reserve = B.JudgeBudget.try_reserve

    def counting(self, usd, tokens):
        reservations.append(1)
        return real_reserve(self, usd, tokens)

    monkeypatch.setattr(B.JudgeBudget, "try_reserve", counting)

    def decide(messages):
        calls.append(1)
        return _default(messages)

    model = _answer(decide)
    _judge(rd, model, model)
    assert calls and len(reservations) == len(calls)  # the guard is the outermost layer of every call


# --- 1. resume never accepts stale or mock reviews --------------------------------------------------------


def test_dry_run_progress_is_never_reused_for_a_real_judging(tmp_path):
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    judge_run(rd, model="mockllm/model", engine="two-pass")  # a dry run leaves progress behind
    assert json.loads((rd.root / TP.PROGRESS_FILE).read_text())
    reviewed: list[str] = []

    def decide(messages):
        if _kind(messages) == "review":
            reviewed.append("x")
        return _default(messages)

    (r,) = _judge(rd, _answer(decide), resume=True)
    assert reviewed and r.stats["chunks_resumed"] == 0
    assert "came from a dry run with the mock judge" in r.coverage
    assert J.DRY_RUN_NOTE not in r.coverage


def test_changed_settings_or_prompts_start_fresh(tmp_path, monkeypatch):
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    _judge(rd, _answer(_default))
    monkeypatch.setattr(TP, "PROMPT_VERSION", "a newer prompt")
    (r,) = _judge(rd, _answer(_default), resume=True)
    assert r.stats["chunks_resumed"] == 0 and "the record, the prompts or the settings have changed" in r.coverage


def test_the_record_fingerprint_covers_actors_metadata_and_links(tmp_path):
    from inspect_ai.log import read_eval_log

    from swarmbench.judge.extract import extract_sample
    from swarmbench.judge.ledger import Link, build_ledger

    path = build_mock_log(tmp_path)
    sample = read_eval_log(str(path), resolve_attachments=True).samples[0]
    lg = build_ledger(sample, extract_sample(sample))
    base = TP.ledger_digest(lg)
    text = next(e for e in lg.events if e.kind == "text")
    text.actor = "agent-2" if text.actor == "agent-1" else "agent-1"
    assert TP.ledger_digest(lg) != base
    lg2 = build_ledger(sample, extract_sample(sample))
    lg2.links.append(Link("file_ref", lg2.events[0].id, "W01"))
    assert TP.ledger_digest(lg2) != base
    lg3 = build_ledger(sample, extract_sample(sample))
    lg3.events[0].meta["note"] = "changed"
    assert TP.ledger_digest(lg3) != base


def test_reviews_by_a_reader_not_used_for_that_part_are_not_reused(tmp_path, monkeypatch):
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    _judge(rd, _answer(_default))
    progress = json.loads((rd.root / TP.PROGRESS_FILE).read_text())
    for sample in progress.values():
        for review in sample["reviews"]:
            review["model"] = "anthropic/claude-haiku-4-5"  # not a reader this judging uses
    (rd.root / TP.PROGRESS_FILE).write_text(json.dumps(progress))
    (r,) = _judge(rd, _answer(_default), resume=True)
    assert r.stats["chunks_resumed"] == 0 and "not reused: read by a model" in r.coverage


# --- 3 and 4. investigation stopped by the budget is a gap; tool rounds admitted at their worst case ------------


def _tight_investigation(monkeypatch) -> None:
    """Part reviews fit; a tool round's worst case doesn't, next to what is held back."""
    monkeypatch.setattr(P, "_usd", lambda model, i, o: 3.0)  # held back: 3 essential calls = $9
    monkeypatch.setattr(J, "default_cap", lambda settings: 10.0)

    def estimate(model, input, config=None):
        return (0.5 if getattr(config, "max_tokens", None) == 12_000 else 1.5), 1000

    monkeypatch.setattr(B, "estimate_call", estimate)


def test_investigation_cut_short_by_the_budget_is_never_a_clean_verdict(tmp_path, monkeypatch):
    _tight_investigation(monkeypatch)
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    (r,) = _judge(rd, _answer(_default))  # an all-zero final answer
    trace = json.loads((rd.root / TP.TRACE_FILE).read_text())[0]
    assert trace["reconcile"]["tools_stopped_by_budget"] and trace["reconcile"]["answer"] is not None
    assert r.headline.startswith("Not fully assessed")
    assert "checking was cut short" in r.headline + r.coverage


def test_tool_rounds_are_admitted_at_their_worst_case(tmp_path, monkeypatch):
    """A tool round projected at 300 output tokens would fit, but its worst case (the prompt so far
    plus its full output allowance) would eat into the held-back reserve: it isn't admitted."""
    from swarmbench.judge.reconcile import RECONCILE_MAX_OUTPUT_TOKENS

    # held back: final answer, repair and summary at $3 each = $9 of a $10 cap; a tool round is
    # projected at $0.01, but its worst case is $1.50
    monkeypatch.setattr(P, "_usd", lambda model, i, o: 3.0 if o >= 1500 else 0.01)
    monkeypatch.setattr(J, "default_cap", lambda settings: 10.0)
    monkeypatch.setattr(B, "estimate_call", lambda model, input, config=None: (
        1.5 if getattr(config, "max_tokens", None) == RECONCILE_MAX_OUTPUT_TOKENS else 0.1, 1000))
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    searched: list[str] = []

    def decide(messages):
        if _kind(messages) == "reconcile" and not any(getattr(m, "role", "") == "tool" for m in messages):
            searched.append("asked")
            return ModelOutput.for_tool_call("mockllm/model", "search", {"query": "work"}, tool_call_id="s1")
        return _default(messages)

    (r,) = _judge(rd, _answer(decide))
    trace = json.loads((rd.root / TP.TRACE_FILE).read_text())[0]
    assert trace["decisions"]["admissions"][0] is False  # refused before the first round
    assert trace["reconcile"]["tools_stopped_by_budget"]
    assert all(u["result_chars"] == len("Not run: the tool limit was reached.")
               for u in trace["reconcile"]["tool_uses"])  # the search never ran
    assert r.headline.startswith("Not fully assessed")


# --- 5. a replay makes the recorded budget decisions -------------------------------------------------------------


def test_replay_reproduces_the_plan_the_stop_and_the_readers(tmp_path, monkeypatch):
    _all_to_fallback(monkeypatch)
    _tight_investigation(monkeypatch)
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    fallback = _answer(_default)
    (first,) = _judge(rd, _answer(_default), fallback)
    first_trace = json.loads((rd.root / TP.TRACE_FILE).read_text())[0]
    assert first_trace["reconcile"]["tools_stopped_by_budget"] and first_trace["cost"]["projected"]["fallback_chunks"]
    saved = tmp_path / "saved.jsonl"
    saved.write_text((rd.root / J.JUDGE_CALLS_FILE).read_text())

    monkeypatch.undo()  # the replay: no forced plan, mock prices (free), a roomy cap
    monkeypatch.setattr(J, "_resolve_models", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no models")))
    (again,) = judge_run(rd, replay=saved, engine="two-pass")  # no ReplayMiss
    trace = json.loads((rd.root / TP.TRACE_FILE).read_text())[0]
    assert trace["decisions"]["plan"]["fallback_chunks"] == first_trace["decisions"]["plan"]["fallback_chunks"]
    assert trace["reconcile"]["tools_stopped_by_budget"]
    assert set(trace["manifest"]["read_by_model"]) == set(first_trace["manifest"]["read_by_model"])
    assert again.coverage.split("; read by")[0] == first.coverage.split("; read by")[0]
    assert again.headline == first.headline
