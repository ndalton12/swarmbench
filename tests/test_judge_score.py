"""The judge's report is written into the Inspect log as a "judge" score."""

from __future__ import annotations

import json

from inspect_ai.log import read_eval_log
from inspect_scout import scan_list, scan_results_df

import swarmbench.judge as J
from swarmbench.judge import judge_run
from swarmbench.paths import RunDir
from tests.fixtures import build_mock_log

LONG = "UNIQUE-PHRASE " + "detail " * 400  # stored as an attachment in the log


def _events_json(sample):
    return [e.model_dump_json() for e in sample.events]


def _assert_only_score_edits_added(before, after):
    """Every original event is still there, byte for byte, and the only new events are
    Inspect's own score-edit provenance records (a small span around a score_edit)."""
    after_json = _events_json(after)
    assert all(e in after_json for e in _events_json(before))
    added = [e for e in after.events if e.model_dump_json() not in set(_events_json(before))]
    assert {e.event for e in added} <= {"span_begin", "span_end", "score_edit"}
    assert any(e.event == "score_edit" for e in added)


def test_judge_score_is_written_and_replaced_on_rejudge(tmp_path):
    rd = RunDir.create("demo", base=tmp_path)
    path = build_mock_log(rd.logs, agent_texts={"agent-1": LONG, "agent-2": "short"},
                          foreign_turns=[{"bridge_of": "agent-2", "verdict": "foreign_identified",
                                          "claimed_actor": "agent-1", "text": "borrowed call"}])
    before = read_eval_log(str(path)).samples[0]

    (report,) = judge_run(rd, model="mockllm/model")
    sample = read_eval_log(str(path)).samples[0]
    score = sample.scores[J.JUDGE_SCORE]
    assert score.value == J.VERDICT_VALUE[report.verdict]
    assert score.answer == report.headline
    assert report.headline in score.explanation and "**Verdict:" in score.explanation.splitlines()[0]
    assert "# Judge report" not in score.explanation
    assert score.metadata["verdict"] == report.verdict and "behaviors" in score.metadata
    assert "interference" in score.metadata["behaviors"]

    # the swarm's own events, attribution data and attachments are untouched
    _assert_only_score_edits_added(before, sample)
    assert sample.store == before.store and sample.attachments == before.attachments

    # re-judging replaces the score and keeps the earlier one in its history
    judge_run(rd, model="mockllm/model")
    again = read_eval_log(str(path)).samples[0].scores[J.JUDGE_SCORE]
    assert again.answer == report.headline
    assert len(again.history) >= 2
    assert any("swarmbench judge" in str(h) for h in again.history)
    _assert_only_score_edits_added(before, read_eval_log(str(path)).samples[0])

    # the Scout replay still opens and links to the same transcript
    for status in scan_list(str(rd.scans)):  # one scan per judge run
        frame = scan_results_df(status.location).scanners["false_success"]
        assert set(frame["transcript_id"]) == {before.uuid}


def test_a_failed_score_write_never_loses_the_report(tmp_path, monkeypatch, caplog):
    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)

    def locked(*args, **kwargs):
        raise PermissionError("file is locked")

    import inspect_ai.log as L

    monkeypatch.setattr(L, "write_eval_log", locked)
    (report,) = judge_run(rd, model="mockllm/model")
    assert rd.report_md.exists() and json.loads(rd.report_json.read_text())[0]["headline"] == report.headline
    assert any("could not add the judge score" in r.message for r in caplog.records)
