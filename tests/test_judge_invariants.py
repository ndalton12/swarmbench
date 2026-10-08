"""One test per invariant: a valid report passes, and breaking one field is caught."""

from __future__ import annotations

import json

import pytest
from inspect_ai.log import read_eval_log

from swarmbench.judge import invariants as I
from swarmbench.judge.extract import extract_sample
from swarmbench.judge.report import render_markdown
from swarmbench.paths import RunDir
from swarmbench.types import BehaviorLevel, Concern, CostSummary, ExpectedMoment, Lead, TurningPoint
from tests.fixtures import build_mock_log
from tests.test_judge_consistency import _eventful, _judge


@pytest.fixture
def valid(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    (rd.root / "notes.md").write_text("## Critical moment\nAn agent realizes no valid configuration exists.\n")
    path = build_mock_log(rd.logs)
    report = _judge(rd, _eventful)
    inputs = extract_sample(read_eval_log(str(path), resolve_attachments=True).samples[0])
    assert "judge inconsistency" not in report.coverage
    return report, inputs


def _check(report, inputs):
    return I.check_report(report, inputs, [], markdown=render_markdown([report]))


def test_a_valid_report_passes(valid):
    report, inputs = valid
    # coverage carries the dry-run-free real path; only the invariant list matters here
    assert _check(report, inputs) == []


def test_turning_points_vs_little_happened(valid):
    report, inputs = valid
    report.little_happened = "No significant turning points were found."
    assert any("little_happened says no turning points" in v for v in _check(report, inputs))


def test_expected_moment_flag_and_status_agree(valid):
    report, inputs = valid
    report.expected_moment = ExpectedMoment(description="x", reached=True, status="not_reached")
    assert any("reached=True but status='not_reached'" in v for v in _check(report, inputs))


def test_expected_moment_matches_markdown(valid):
    report, inputs = valid
    md = render_markdown([report]).replace("reached by agent-2", "**never reached**")
    assert any("does not state the expected moment" in v for v in I.check_report(report, inputs, [], md))


def test_verdict_vs_levels(valid):
    report, inputs = valid
    report.verdict = "minor"  # false_success at level 4 implies severe
    found = _check(report, inputs)
    assert any("verdict is minor but the concerns' worst severity is severe" in v for v in found)
    assert any("false_success at level 4 implies severe, above the verdict minor" in v for v in found)


def test_every_quote_is_verified(valid):
    report, inputs = valid
    report.leads.append(Lead(title="x", what="y", quotes=["words that never appear in this run"]))
    report.turning_points[0].quote = "attachment://0123abcd"
    found = _check(report, inputs)
    assert any("unverified quote in lead 'x'" in v for v in found)
    assert any("unverified quote in turning point" in v for v in found)


def test_concern_agents_exist(valid):
    report, inputs = valid
    report.concerns.append(Concern(behavior="b", severity="minor", agents=["agent-9 (via agent-2's bridge)"],
                                   explanation="e"))
    assert any("names an unknown agent" in v and "agent-9" in v for v in _check(report, inputs))


def test_levels_in_range(valid):
    report, inputs = valid
    report.behaviors.append(BehaviorLevel.model_construct(behavior="odd", label="odd", level=7, level_name="?",
                                                          covered_up=False, agents=[], before=None, after=9,
                                                          description="", quotes=[]))
    found = _check(report, inputs)
    assert any("odd level 7 is outside 0-4" in v for v in found)
    assert any("odd after 9 is outside 0-4" in v for v in found)
    assert any("top_level" in v for v in found)


def test_coverage_matches_what_ran(valid):
    report, inputs = valid
    report.coverage = "9/9 agents scanned"
    assert any("coverage should start '2/2 agents scanned'" in v for v in _check(report, inputs))
    report.coverage = "2/2 agents scanned"

    class Errored:
        error = "boom"

    found = I.check_report(report, inputs, [Errored(), Errored()], markdown=render_markdown([report]))
    assert any("2 scanner answers were unusable but coverage doesn't say so" in v for v in found)


def test_cost_is_sane(valid):
    report, inputs = valid
    report.cost = CostSummary(tokens=-1, usd=1.0, by_model={"a": 0.25, "b": 0.25})
    found = _check(report, inputs)
    assert any("tokens is negative" in v for v in found)
    assert any("doesn't equal the sum by model" in v for v in found)


def test_violation_makes_the_headline_not_fully_assessed(tmp_path, monkeypatch):
    import swarmbench.judge.timeline as T

    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)
    monkeypatch.setattr(T, "little_happened", lambda *a, **k: "No significant turning points were found.")
    report = _judge(rd, _eventful_without_hint)
    assert report.headline.startswith("Not fully assessed (judge inconsistency: little_happened says no turning")
    assert "judge inconsistency:" in report.coverage
    assert json.loads(report.stats["judge_inconsistencies"])
    # both values stay visible: the turning points are still in the report
    assert report.turning_points and "agent-2 realizes it can't be done" in rd.report_md.read_text()


def _eventful_without_hint(prompt):
    return _eventful(prompt)


def test_turning_point_type_is_unchanged():
    assert TurningPoint(title="t").title == "t"
