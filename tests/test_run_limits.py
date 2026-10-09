"""A swarm that Inspect cancels at its time (or cost) limit ended normally; it didn't fail."""

from __future__ import annotations

from types import SimpleNamespace

import inspect_ai.log as ilog

from swarmbench.runner import runs


def _patch(monkeypatch, limit, problems):
    outcome = {"ok": False, "outcome": "sample_error", "problems": problems}
    sample = SimpleNamespace(
        epoch=1,
        error=None,
        limit=SimpleNamespace(type=limit) if limit else None,
        metadata={"swarm_outcome": outcome},
    )
    monkeypatch.setattr(ilog, "read_eval_log", lambda *a, **k: SimpleNamespace(status="success", error=None))
    monkeypatch.setattr(ilog, "read_eval_log_sample_summaries", lambda *a, **k: [sample])


def test_time_limit_is_a_normal_end(monkeypatch, tmp_path):
    _patch(monkeypatch, "time", ["sample error: cancelled"])
    assert runs.log_problems([tmp_path / "x.eval"]) == ([], ["ended at its time limit"])


def test_time_limit_given_as_a_plain_string_is_a_normal_end(monkeypatch, tmp_path):
    """Inspect's sample summaries give the limit as a string ("time"), not an object."""
    outcome = {"ok": False, "outcome": "sample_error", "problems": ["sample error: cancelled"]}
    sample = SimpleNamespace(epoch=1, error=None, limit="time", metadata={"swarm_outcome": outcome})
    monkeypatch.setattr(ilog, "read_eval_log", lambda *a, **k: SimpleNamespace(status="success", error=None))
    monkeypatch.setattr(ilog, "read_eval_log_sample_summaries", lambda *a, **k: [sample])
    assert runs.log_problems([tmp_path / "x.eval"]) == ([], ["ended at its time limit"])


def test_cancelled_without_a_limit_still_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, None, ["sample error: cancelled"])
    assert runs.log_problems([tmp_path / "x.eval"])[0] == ["sample error: cancelled"]


def test_other_problems_at_the_limit_still_fail(monkeypatch, tmp_path):
    _patch(monkeypatch, "time", ["sample error: cancelled", "agent-2 crashed: boom"])
    assert "agent-2 crashed: boom" in runs.log_problems([tmp_path / "x.eval"])[0]


def test_a_rejudge_reassesses_how_the_run_ended(monkeypatch, tmp_path):
    """A run recorded as "failed: sample error: cancelled" (its time limit) reads "done" after a re-judge."""
    from swarmbench.paths import RunDir
    from swarmbench.types import RunStatus

    rd = RunDir.create("rival-swarms", base=tmp_path)
    rd.logs.mkdir(parents=True, exist_ok=True)
    (rd.logs / "x.eval").write_text("")
    outcome = {"ok": False, "outcome": "sample_error", "problems": ["sample error: cancelled"]}
    sample = SimpleNamespace(epoch=1, error=None, limit="time", metadata={"swarm_outcome": outcome})
    monkeypatch.setattr(ilog, "read_eval_log", lambda *a, **k: SimpleNamespace(status="success", error=None))
    monkeypatch.setattr(ilog, "read_eval_log_sample_summaries", lambda *a, **k: [sample])
    old = RunStatus(
        run_id=rd.run_id, scenario="rival-swarms", state="failed", error="sample error: cancelled"
    )
    new = runs.reassess_outcome(rd, old)
    assert (new.state, new.error) == ("done", "ended at its time limit")
    stopped = old.model_copy(update={"state": "stopped", "error": "stopped by request"})
    assert runs.reassess_outcome(rd, stopped) == stopped  # a user's stop is left alone
