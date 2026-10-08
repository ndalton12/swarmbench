"""The expected moment and turning points can't be silently lost: robust JSON reading,
'unclear' instead of 'not reached', one match is enough, and little_happened agrees."""

from __future__ import annotations

import json

import anyio

import swarmbench.judge as J
from swarmbench.judge import mock_answer
from swarmbench.judge.timeline import _json_object, little_happened
from swarmbench.paths import RunDir
from swarmbench.types import ExpectedMoment, TurningPoint
from tests.fixtures import build_mock_log
from tests.test_judge import _answer_model

A2 = "I could not find a valid configuration; I think the problem may have no solution"
HINT = "## Critical moment\nAn agent realizes no valid configuration exists.\n"


def test_json_reading_survives_prose_and_fences():
    payload = {"turning_points": [{"title": "x"}], "expected_moment": None}
    body = json.dumps(payload)
    assert _json_object(f"Here you go:\n```json\n{body}\n```\nThanks {{}}", key="turning_points") == payload
    assert _json_object(f"Note {{draft}} first. {body} trailing {{x}}", key="turning_points") == payload
    assert _json_object(body[:-20], key="turning_points") is None  # cut off: unreadable, not empty


def _judge(rd, tp_reply):
    model = _answer_model(lambda p: tp_reply(p) if '"turning_points"' in p else mock_answer(p))

    async def go():
        original = J._resolve_models
        J._resolve_models = lambda m, judge_model=None: J._Models(model, model, model, model)
        try:
            return await J._judge_async(rd, None, engine="scanners")
        finally:
            J._resolve_models = original

    return anyio.run(go)[0]


def _item(prompt, text):
    return next((ln.split("]")[0][1:] for ln in prompt.splitlines() if text[:40] in ln), "D1")


def _point(prompt, **extra):
    return {"title": "agent-2 realizes it can't be done", "kind": "impossible", "item": _item(prompt, A2),
            "agents": ["agent-2"], "quote": A2, "significance": 3, **extra}


def test_cut_off_answer_is_a_gap_not_no_turning_points(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    (rd.root / "notes.md").write_text(HINT)
    build_mock_log(rd.logs)
    r = _judge(rd, lambda p: json.dumps({"turning_points": [_point(p)]})[:-30])  # truncated
    assert "turning points could not be analysed" in r.coverage
    assert r.headline.startswith("Not fully assessed")
    assert "No significant turning points" not in r.little_happened
    assert r.expected_moment is None  # not claimed either way


def test_one_matching_turning_point_is_enough(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    (rd.root / "notes.md").write_text(HINT)
    build_mock_log(rd.logs)
    # the model forgot to fill expected_moment, but marked the point as the moment
    r = _judge(rd, lambda p: json.dumps({"turning_points": [_point(p, matches_expected_moment=True)],
                                         "expected_moment": None}))
    em = r.expected_moment
    assert em.reached and em.status == "reached" and em.turning_point == 0 and em.agents == ["agent-2"]
    assert "never reached" not in rd.report_md.read_text()


def test_ambiguous_answer_is_unclear_not_false(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    (rd.root / "notes.md").write_text(HINT)
    build_mock_log(rd.logs)
    r = _judge(rd, lambda p: json.dumps({"turning_points": [_point(p)]}))  # no expected_moment at all
    assert r.expected_moment.status == "unclear" and not r.expected_moment.reached
    assert "scenario needs fixing" not in r.little_happened
    assert "unclear" in rd.report_md.read_text()


def test_explicit_not_reached_with_no_match():
    em = ExpectedMoment(description="x", reached=False, status="not_reached")
    assert "scenario needs fixing" in little_happened([], em, _inputs(), 0)


def test_little_happened_never_claims_none_when_there_are_points():
    note = little_happened([TurningPoint(title="t")], None, _inputs(), 0)
    assert "No significant turning points" not in note


def _inputs():
    from swarmbench.judge.extract import AgentView, SampleInputs

    return SampleInputs(scenario="s", run_id="r", sample_id=1, epoch=1, agents=[AgentView(name="agent-1")],
                        foreign=[], agents_meta=[], messages=[], monitor_flags=[], bridge_summary={},
                        bridge_uses=[], protected_hashes={}, problems=[], agent_usage={}, outcome="")
