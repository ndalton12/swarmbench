"""Regression tests for Codex's last quick check of the two-pass judge, one per item.
Mock and replay only."""

from __future__ import annotations

import json
from datetime import timedelta

import anyio
import pytest

import swarmbench.judge as J
from swarmbench.judge import budget as B
from swarmbench.judge import judge_run
from swarmbench.judge import two_pass as TP
from swarmbench.paths import RunDir
from swarmbench.types import CostSummary
from tests.fixtures import build_mock_log
from tests.test_judge_fixes3 import _answer, _judge
from tests.test_judge_two_pass import _default

# --- 1. the resume fingerprint includes timestamps ----------------------------------------------------------


def test_the_record_fingerprint_includes_timestamps(tmp_path):
    from inspect_ai.log import read_eval_log

    from swarmbench.judge.extract import extract_sample
    from swarmbench.judge.ledger import build_ledger

    path = build_mock_log(tmp_path)
    sample = read_eval_log(str(path), resolve_attachments=True).samples[0]
    lg = build_ledger(sample, extract_sample(sample))
    base = TP.ledger_digest(lg)
    lg.events[-1].time = lg.events[-1].time + timedelta(seconds=1)
    assert TP.ledger_digest(lg) != base


# --- 2. retries happen in our layer, each with its own reservation ------------------------------------------


class Overloaded(Exception):
    pass


class FakeModel:
    """Fails with a retryable error ``failures`` times, then answers."""

    def __init__(self, failures: int, error: type[Exception] = Overloaded) -> None:
        self.failures, self.error, self.configs = failures, error, []

    async def generate(self, input, **kwargs):
        self.configs.append(kwargs["config"])
        if len(self.configs) <= self.failures:
            raise self.error("try again")
        return "answer"

    def should_retry(self, ex):
        return isinstance(ex, Overloaded)

    def __str__(self) -> str:
        return "fake/model"


def _guarded(model, cap: float = 10.0):
    reservations = []
    budget = B.JudgeBudget(cap_usd=cap, estimate_fn=lambda m, i, c: (1.0, 10),
                           spent_fn=lambda: CostSummary(tokens=0, usd=0.0))
    real = budget.try_reserve

    def counting(usd, tokens):
        reservations.append(usd)
        return real(usd, tokens)

    budget.try_reserve = counting
    budget.guard(model)
    return budget, reservations


def test_a_retryable_failure_is_retried_with_a_fresh_reservation(monkeypatch):
    monkeypatch.setattr(B, "RETRY_BASE_SECONDS", 0.0)
    model = FakeModel(failures=2)
    _, reservations = _guarded(model)
    assert anyio.run(model.generate, ["prompt"]) == "answer"
    assert len(model.configs) == 3 and len(reservations) == 3  # one reservation per attempt
    assert all(c.max_retries == 0 for c in model.configs)  # Inspect's own retries are off


def test_retries_stop_at_the_limit_and_at_the_cap(monkeypatch):
    monkeypatch.setattr(B, "RETRY_BASE_SECONDS", 0.0)
    model = FakeModel(failures=99)
    _guarded(model)
    with pytest.raises(Overloaded):
        anyio.run(model.generate, ["prompt"])
    assert len(model.configs) == B.JUDGE_MAX_RETRIES + 1


def test_each_retry_needs_room_under_the_cap(monkeypatch):
    """Failed attempts are paid for: a retry is reserved like any call, so at a $2 cap and $1 an
    attempt, the third attempt is refused instead of being sent."""
    monkeypatch.setattr(B, "RETRY_BASE_SECONDS", 0.0)
    spent = [0.0]

    class Paid(FakeModel):
        async def generate(self, input, **kwargs):
            spent[0] += 1.0
            return await super().generate(input, **kwargs)

    model = Paid(failures=99)
    budget, _ = _guarded(model, cap=2.0)
    budget.spent_fn = lambda: CostSummary(tokens=0, usd=spent[0])
    with pytest.raises(B.JudgeBudgetExhausted):
        anyio.run(model.generate, ["prompt"])
    assert len(model.configs) == 2


def test_a_failure_that_is_not_retryable_is_not_retried():
    model = FakeModel(failures=1, error=ValueError)
    _guarded(model)
    with pytest.raises(ValueError):
        anyio.run(model.generate, ["prompt"])
    assert len(model.configs) == 1


# --- 3. the reserve covers the essential calls at their full output allowance -------------------------------


def test_the_reserve_matches_the_essential_calls_max_tokens():
    from swarmbench.judge.chunks import Chunk
    from swarmbench.judge.projection import _usd, essential_max_tokens, project
    from swarmbench.judge.reconcile import RECONCILE_MAX_OUTPUT_TOKENS

    opus = "anthropic/claude-opus-5-5"
    chunks = [Chunk(id="C01", events=["L0001"])]
    p = project(chunks=chunks, chunk_chars={"C01": 40_000}, review_system_chars=20_000,
                reconcile_fixed_chars=60_000, summary_extra_chars=10_000, main_model=opus,
                fallback_model=opus, cap_usd=100.0, triggers={})
    essential = [c for c in p.calls if not c.what.startswith(("review", "reconcile: tool"))]
    assert essential_max_tokens()[:2] == (RECONCILE_MAX_OUTPUT_TOKENS, RECONCILE_MAX_OUTPUT_TOKENS)
    worst = sum(_usd(opus, c.input_tokens, cap) for c, cap in zip(essential, essential_max_tokens(), strict=True))
    assert p.held_usd == pytest.approx(worst, rel=1e-3)
    assert p.held_usd > sum(c.usd for c in essential)  # more than the expected sizes
    assert p.held_tokens >= sum(c.input_tokens for c in essential) + sum(essential_max_tokens())


# --- 4. a resumed judging replays from its own session --------------------------------------------------------


def test_an_appended_resume_recording_replays_its_own_session(tmp_path, monkeypatch):
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    # session 1: the budget refuses every call
    with monkeypatch.context() as m:
        m.setattr(B, "estimate_call", lambda model, input, config=None: (None, 10**9))
        (first,) = _judge(rd, _answer(_default))
    assert first.headline.startswith("Not fully assessed")
    # session 2: resumed with room; the same review prompts now succeed
    (second,) = _judge(rd, _answer(_default), resume=True)
    assert not second.headline.startswith("Not fully assessed")
    lines = [json.loads(x) for x in (rd.root / J.JUDGE_CALLS_FILE).read_text().splitlines()]
    assert [r["session"] for r in lines if "session" in r and "key" not in r] == [1, 2]

    saved = tmp_path / "saved.jsonl"
    saved.write_text((rd.root / J.JUDGE_CALLS_FILE).read_text())
    monkeypatch.setattr(J, "_resolve_models", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no models")))
    (again,) = judge_run(rd, replay=saved, engine="two-pass")
    assert again.headline == second.headline  # session 2's successes, not session 1's refusals
    trace = json.loads((rd.root / TP.TRACE_FILE).read_text())[0]
    assert all(c["ok"] for c in trace["chunks"])
