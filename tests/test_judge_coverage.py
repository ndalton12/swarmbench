"""The judge's spending cap, and reports that never read as clean when the run
was not fully assessed."""

from __future__ import annotations

import anyio
import pytest

import swarmbench.judge as J
from swarmbench.judge import judge_run
from swarmbench.judge.budget import JudgeBudget, default_cap
from swarmbench.paths import RunDir
from swarmbench.status import read_status
from swarmbench.types import CostSummary, RunStatus
from tests.fixtures import build_mock_log
from tests.test_judge import _answer_model

NO = "Nothing of note.\nANSWER: no"


def _judge_real_path(rd, model):
    """Run the judge as a non-dry run, with a mock model standing in for every role."""

    async def go():
        original = J._resolve_models
        J._resolve_models = lambda m, judge_model=None: J._Models(model, model, model, model)
        try:
            return await J._judge_async(rd, None)
        finally:
            J._resolve_models = original

    return anyio.run(go)


def _status(rd):
    rd.status.write_text(RunStatus(run_id=rd.run_id, scenario="demo").model_dump_json())


# --- the cap -----------------------------------------------------------------


def test_default_cap():
    from types import SimpleNamespace as NS

    from swarmbench.costs import judge_allowance

    assert default_cap(None) == 10.0
    assert default_cap(NS(max_cost=None, advanced=NS(judge_max_cost=None))) == 10.0
    assert default_cap(NS(max_cost=40.0, advanced=NS(judge_max_cost=None))) == judge_allowance(40.0)
    assert default_cap(NS(max_cost=40.0, advanced=NS(judge_max_cost=2.5))) == 2.5


def test_budget_is_per_sample_and_sticky():
    spent = {"usd": 0.0}
    budget = JudgeBudget(cap_usd=1.0, spent_fn=lambda: CostSummary(tokens=0, usd=spent["usd"]))
    budget.start_sample()
    spent["usd"] = 0.5
    assert not budget.exhausted()
    spent["usd"] = 1.2
    assert budget.exhausted()
    spent["usd"] = 1.2
    budget.start_sample()  # next sample measures from here
    assert not budget.exhausted()


def test_unpriced_models_fall_back_to_a_token_cap():
    budget = JudgeBudget(cap_usd=5.0, token_cap=100, spent_fn=lambda: CostSummary(tokens=150, usd=None))
    assert budget.exhausted() and "tokens for unpriced models" in budget.gap()


def test_cap_stops_scanning_and_report_says_so(tmp_path, monkeypatch):
    rd = RunDir.create("demo", base=tmp_path)
    _status(rd)
    build_mock_log(rd.logs)
    calls = {"n": 0}

    def growing_spend():
        calls["n"] += 1
        return CostSummary(tokens=0, usd=0.3 * calls["n"])

    monkeypatch.setattr(J, "JudgeBudget", lambda cap_usd: JudgeBudget(cap_usd=1.0, spent_fn=growing_spend))
    summarizer_prompts = []

    def decide(prompt):
        if '"headline"' in prompt:
            summarizer_prompts.append(prompt)
        return NO

    (report,) = _judge_real_path(rd, _answer_model(decide))
    assert "the judge's budget ran out" in report.coverage
    assert report.headline.startswith("Not fully assessed (the judge's budget ran out")
    assert not summarizer_prompts, "no summarizer call once the budget is gone"
    hits = J.json.loads((rd.root / J.JUDGE_HITS_FILE).read_text())[0]["hits"]
    assert 0 < len(hits) < 16, "scanning stopped part way"
    assert read_status(rd).headline == report.headline


def test_spend_is_recorded_even_if_judging_crashes(tmp_path, monkeypatch):
    rd = RunDir.create("demo", base=tmp_path)
    _status(rd)
    build_mock_log(rd.logs)

    async def boom(*args, **kwargs):
        raise RuntimeError("scanner crashed")

    monkeypatch.setattr(J, "run_team_scanners", boom)
    with pytest.raises(RuntimeError):
        judge_run(rd, model="mockllm/model")
    # the agent scanners ran before the crash, and their spend was saved
    assert read_status(rd).judge_cost.tokens > 0


# --- never a clean headline when coverage is incomplete --------------------------


def test_fully_assessed_run_reads_clean(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)
    (report,) = _judge_real_path(rd, _answer_model(lambda prompt: NO))
    assert report.verdict == "none"
    assert report.headline.startswith("No concerning behavior found")


def test_crashed_agent_means_not_fully_assessed(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    _status(rd)
    build_mock_log(rd.logs, agent_stops=[{"agent": "agent-2", "reason": "crashed: boom"},
                                         {"agent": "agent-1", "reason": "finished"}])
    (report,) = _judge_real_path(rd, _answer_model(lambda prompt: NO))
    assert report.verdict == "none"  # verdict values unchanged...
    assert report.headline.startswith("Not fully assessed (agent-2 crashed: boom)")  # ...but never clean
    assert "nothing concerning" not in report.headline.lower() or "in what was checked" in report.headline
    assert "agent-1" not in report.headline  # a normal finish is not a gap
    assert read_status(rd).headline == report.headline
    assert "not fully assessed" in rd.report_md.read_text()


def test_budget_stop_is_not_a_finish(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs, agent_stops=[{"agent": "agent-1", "reason": "budget"}])
    (report,) = _judge_real_path(rd, _answer_model(lambda prompt: NO))
    assert "agent-1 ran out of its token budget before finishing" in report.headline


def test_failed_scanner_means_not_fully_assessed(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)

    def flaky(prompt):
        return "I can't say." if "fabricated result" in prompt else NO

    (report,) = _judge_real_path(rd, _answer_model(flaky))
    assert report.headline.startswith("Not fully assessed (2 check(s) had no usable answer)")


def test_run_problems_mean_not_fully_assessed(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs, problems=["container watcher stopped in team-swarm (evidence lost from that point)"])
    (report,) = _judge_real_path(rd, _answer_model(lambda prompt: NO))
    assert report.headline.startswith("Not fully assessed (1 run problem(s) recorded)")


def test_dry_run_is_never_clean(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)
    (report,) = judge_run(rd, model="mockllm/model")
    assert report.headline.startswith("Not fully assessed (dry run")
