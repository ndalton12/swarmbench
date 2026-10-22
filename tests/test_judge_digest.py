"""Condensing part notes before the final review, for runs too large to review in one go."""

from __future__ import annotations

import json
import re

import anyio

import swarmbench.judge.two_pass as TP
from swarmbench.judge.digest import SYSTEM as DIGEST_SYSTEM
from swarmbench.judge.digest import condense, summary
from swarmbench.judge.reconcile import fit_user_prompt, reconcile_user_prompt
from swarmbench.judge.review import ChunkReview, Note
from swarmbench.paths import RunDir
from tests.fixtures import build_mock_log
from tests.test_judge_two_pass import LIE, _kind, _model, _run, _text, mock_reconcile


class _Manifest:
    def __init__(self) -> None:
        self.reads: list[tuple[str, bool]] = []

    def record(self, call, model, events, ok=True, note=""):
        self.reads.append((call, ok))


class _Workspace:
    def render(self) -> str:
        return "<workspace_changes>(none)</workspace_changes>"


def _notes():
    kept = Note(type="behavior", text="agent-1 killed other users' jobs", agents=["agent-1"], sources=["L0007"],
                chunk="C01")  # fmt: skip
    routine = [Note(type="observation", text=f"agent-1 retried a compile ({i})", agents=["agent-1"],
                    sources=[f"L{i:04d}"], chunk=f"C{i:02d}") for i in range(10, 30)]  # fmt: skip
    return kept, routine


def _files():
    kept, routine = _notes()
    return {"agent-1": [kept, *routine], "team": []}, kept


def test_condense_keeps_rating_notes_word_for_word_and_cites_only_given_entries():
    files, kept = _files()

    def answer(messages):
        assert DIGEST_SYSTEM in _text(messages[0])
        return json.dumps({"notes": [
            {"type": "observation", "text": "agent-1 retried compiles many times", "agents": ["agent-1"],
             "sources": ["L0010", "L0011", "L9999"]},
            {"type": "observation", "text": "made up", "sources": ["L9999"]},
        ]})  # fmt: skip

    result = anyio.run(lambda: condense(
        files, lambda fs: sum(len(v) for v in fs.values()) <= 3, model=_model(answer), model_name="m",
        limiter=None, manifest=_Manifest(), agents={"agent-1"}))  # fmt: skip
    notes = result.files["agent-1"]
    assert notes[0] is kept  # untouched
    assert [n.text for n in notes[1:]] == ["agent-1 retried compiles many times"]
    assert notes[1].sources == ["L0010", "L0011"]  # L9999 was never in the notes it replaced
    assert result.before == 20 and result.after == 1 and result.calls == 1
    assert "20 routine part notes were condensed into 1" in summary(result)


def test_a_batch_that_cannot_be_condensed_keeps_its_notes():
    files, _ = _files()
    result = anyio.run(lambda: condense(
        files, lambda fs: False, model=_model(lambda m: "not json"), model_name="m", limiter=None,
        manifest=_Manifest(), agents={"agent-1"}))  # fmt: skip
    assert result.files["agent-1"] == files["agent-1"]
    assert result.failed >= 1 and "could not be condensed" in summary(result)


def test_fit_user_prompt_only_changes_oversized_input():
    files, _ = _files()
    reviews = [ChunkReview(chunk=None, notes=files["agent-1"], ok=True)]  # type: ignore[arg-type]
    full = reconcile_user_prompt(files, reviews, [], _Workspace(), "all read")
    assert fit_user_prompt(files, reviews, [], _Workspace(), "all read") == (full, None)
    text, note = fit_user_prompt(files, reviews, [], _Workspace(), "all read", budget=len(full) // 2)
    assert len(text) <= len(full) // 2
    assert "agent-1 killed other users' jobs" in text and "sources: L0007" in text
    assert note and "shortened" in note


def test_a_run_too_large_for_one_final_review_is_condensed_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(TP, "RECONCILE_PROMPT_BUDGET_CHARS", 3000)
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs, agent_texts={"agent-1": LIE, "agent-2": "Working on it."})
    seen = {"digest": 0, "reconcile": 0}

    def decide(messages):
        system = _text(messages[0])
        if DIGEST_SYSTEM in system:
            seen["digest"] += 1
            return json.dumps(
                {
                    "notes": [
                        {
                            "type": "observation",
                            "text": "routine work, condensed",
                            "sources": [_text(messages[1]).split("sources: ")[1].split()[0].strip(",")],
                        }
                    ]
                }
            )
        kind = _kind(messages)
        if kind == "review":
            src = re.findall(r"\bL\d{4}\b", _text(messages[-1]))[0]
            return json.dumps({"notes": [{"type": "observation", "agents": ["agent-1"], "text": "x" * 400,
                                          "sources": [src]} for _ in range(12)]})  # fmt: skip
        if kind == "reconcile":
            seen["reconcile"] += 1
            return mock_reconcile(system + "\n" + _text(messages[1]))
        from swarmbench.judge import mock_answer

        return mock_answer(_text(messages[-1]))

    report = _run(rd, decide)
    assert seen["digest"] >= 1 and seen["reconcile"] >= 1
    assert any("condensed" in g for g in report.gaps), report.gaps
