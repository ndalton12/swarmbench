"""One judge model (Opus 5.5) by default; a single override; a note on self-assessment."""

from __future__ import annotations

import anyio

import swarmbench.judge as J
from swarmbench.judge import mock_answer
from swarmbench.paths import RunDir
from tests.fixtures import build_mock_log
from tests.test_judge import _answer_model


def test_defaults_are_one_judge_model():
    assert J.DEFAULT_JUDGE_MODEL == "anthropic/claude-opus-5-5"
    assert J.DEFAULT_JUDGE_MODELS == ["anthropic/claude-opus-5-5"]
    assert J.DEFAULT_JUDGE_FALLBACK_MODEL == "anthropic/claude-sonnet-5-5"


def test_every_role_uses_one_model(monkeypatch):
    import inspect_ai.model as M

    built: list[str] = []
    monkeypatch.setattr(M, "get_model", lambda name, **kw: built.append(name) or name)
    models = J._resolve_models(None)
    assert {models.scanner, models.screen, models.confirm, models.summarizer} == {"anthropic/claude-opus-5-5"}
    built.clear()
    models = J._resolve_models(None, "anthropic/claude-sonnet-5-5")  # advanced.judge_model
    assert {models.scanner, models.screen, models.confirm, models.summarizer} == {"anthropic/claude-sonnet-5-5"}
    models = J._resolve_models("openai/gpt-x")  # --judge-model
    assert {models.scanner, models.screen, models.confirm, models.summarizer} == {"openai/gpt-x"}


def test_self_assessment_note():
    agents = [{"model": "anthropic/claude-opus-5-5"}, {"model": "anthropic/claude-sonnet-5-5"}]
    note = J.self_assessment_note("anthropic/claude-opus-5-5", agents)
    assert note == ("judge model is also a model under test: anthropic/claude-opus-5-5; "
                    "self-assessment bias possible")
    assert J.self_assessment_note("anthropic/claude-haiku-4-5", agents) is None
    assert J.self_assessment_note("mockllm/model", [{"model": "mockllm/model"}]) is None  # dry runs


def test_note_appears_in_coverage_when_agents_share_the_judge_model(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs, agent_model="anthropic/claude-opus-5-5")
    model = _answer_model(lambda p: mock_answer(p))

    async def go():
        original = J._resolve_models
        J._resolve_models = lambda m, judge_model=None: J._Models(model, model, model, model)
        try:
            return await J._judge_async(rd, None)
        finally:
            J._resolve_models = original

    (report,) = anyio.run(go)
    assert "judge model is also a model under test: anthropic/claude-opus-5-5" in report.coverage


def test_judge_run_accepts_a_fallback_model(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)
    (report,) = J.judge_run(rd, model="mockllm/model", fallback_model="anthropic/claude-sonnet-5-5")
    assert report.verdict
