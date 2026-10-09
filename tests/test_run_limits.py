"""A swarm that Inspect cancels at its time (or cost) limit ended normally; it didn't fail."""

from __future__ import annotations

from types import SimpleNamespace

import inspect_ai.log as ilog

from swarmbench.runner import runs


def _patch(monkeypatch, limit, problems):
    outcome = {"ok": False, "outcome": "sample_error", "problems": problems}
    sample = SimpleNamespace(
        epoch=1, error=None, limit=SimpleNamespace(type=limit) if limit else None, metadata={"swarm_outcome": outcome}
    )
    monkeypatch.setattr(ilog, "read_eval_log", lambda *a, **k: SimpleNamespace(status="success", error=None))
    monkeypatch.setattr(ilog, "read_eval_log_sample_summaries", lambda *a, **k: [sample])


def test_time_limit_is_a_normal_end(monkeypatch, tmp_path):
    _patch(monkeypatch, "time", ["sample error: cancelled"])
    assert runs.log_problems([tmp_path / "x.eval"]) == ([], ["ended at its time limit"])


def test_cancelled_without_a_limit_still_fails(monkeypatch, tmp_path):
    _patch(monkeypatch, None, ["sample error: cancelled"])
    assert runs.log_problems([tmp_path / "x.eval"])[0] == ["sample error: cancelled"]


def test_other_problems_at_the_limit_still_fail(monkeypatch, tmp_path):
    _patch(monkeypatch, "time", ["sample error: cancelled", "agent-2 crashed: boom"])
    assert "agent-2 crashed: boom" in runs.log_problems([tmp_path / "x.eval"])[0]
