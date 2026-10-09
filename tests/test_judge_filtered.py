"""A judge call the provider's safety filter stops goes once to a model from another provider
(GPT-6.1 Sol by default); what stays stopped is reported as the filter, not as unreadable JSON.
Mock and replay only."""

from __future__ import annotations

import json
from typing import Any

import anyio
from inspect_ai.model import ModelOutput, get_model

import swarmbench.judge as J
from swarmbench.judge import judge_run
from swarmbench.judge.calls import FILTERED_TEXT, filtered, reroute_filtered
from swarmbench.paths import RunDir
from tests.fixtures import build_mock_log
from tests.test_judge_two_pass import _default, _kind


def _model(decide, seen: list[str] | None = None, name: str = "mockllm/model"):
    def outputs(input, tools, tool_choice, config):
        if seen is not None:
            seen.append(_kind(list(input)))
        out = decide(list(input))
        return out if isinstance(out, ModelOutput) else ModelOutput.from_content(name, out)

    return get_model("mockllm/model", custom_outputs=outputs)


def _stopped() -> ModelOutput:
    return ModelOutput.from_content("mockllm/model", "", stop_reason="content_filter")


def _judge(rd: RunDir, main: Any, other: Any) -> Any:
    async def go():
        saved = J._resolve_models, J._resolve_fallback
        J._resolve_models = lambda m, judge_model=None: J._Models(main, main, main, main)
        J._resolve_fallback = lambda m, name: other if name == J.DEFAULT_JUDGE_BLOCKED_MODEL else main
        try:
            return await J._judge_async(rd, None, engine="two-pass")
        finally:
            J._resolve_models, J._resolve_fallback = saved

    return anyio.run(go)


def _reviews_stopped(messages):
    return _stopped() if _kind(messages) == "review" else _default(messages)


# --- the wrapper ---------------------------------------------------------------------------------


def test_a_stopped_answer_is_asked_of_the_other_model_once():
    events: list[str] = []
    other_calls: list[str] = []
    main = reroute_filtered(_model(lambda m: _stopped()), lambda: _model(lambda m: '{"ok": 1}', other_calls),
                            events.append)
    out = anyio.run(main.generate, "hi")
    assert out.completion == '{"ok": 1}' and events == ["rerouted"] and len(other_calls) == 1
    fine = reroute_filtered(_model(lambda m: "fine"), lambda: (_ for _ in ()).throw(AssertionError("not asked")))
    assert anyio.run(fine.generate, "hi").completion == "fine"
    events.clear()
    none = reroute_filtered(_model(lambda m: _stopped()), lambda: None, events.append)
    assert filtered(anyio.run(none.generate, "hi")) and events == ["unavailable"]
    events.clear()
    both = reroute_filtered(_model(lambda m: _stopped()), lambda: _model(lambda m: _stopped()), events.append)
    assert filtered(anyio.run(both.generate, "hi")) and events == ["also stopped"]


# --- a whole judging -----------------------------------------------------------------------------


def test_parts_the_filter_stops_are_read_by_the_other_model_and_the_report_says_so(tmp_path):
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    other_seen: list[str] = []
    (r,) = _judge(rd, _model(_reviews_stopped), _model(_default, other_seen, "openai/gpt-6.1-sol"))
    assert "review" in other_seen and "reconcile" not in other_seen  # only the stopped calls
    assert r.fully_assessed and not r.gaps
    note = next(n for n in r.judge_notes if "safety filter" in n)
    assert "answered by openai/gpt-6.1-sol instead" in note
    assert "read by openai/gpt-6.1-sol" in r.coverage  # the parts it wrote are credited to it

    # resuming never passes its reviews off as the main model's: they are read again
    from swarmbench.judge.two_pass import PROGRESS_FILE

    progress = json.loads((rd.root / PROGRESS_FILE).read_text())
    assert {rv["model"] for s in progress.values() for rv in s["reviews"]} == {"openai/gpt-6.1-sol"}

    # the recording replays the same judging: the stopped answer, then the other model's
    saved = tmp_path / "saved.jsonl"
    saved.write_text((rd.root / J.JUDGE_CALLS_FILE).read_text())
    assert any(json.loads(line).get("stop_reason") == "content_filter" for line in saved.read_text().splitlines())
    (again,) = judge_run(rd, replay=saved, engine="two-pass")
    assert again.fully_assessed and any("answered by" in n for n in again.judge_notes)


def test_with_no_other_model_the_gap_names_the_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(J, "DEFAULT_JUDGE_BLOCKED_MODEL", "none")
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)
    (r,) = _judge(rd, _model(_reviews_stopped), _model(_default))
    assert not r.fully_assessed
    assert any(FILTERED_TEXT in g for g in r.gaps) and not any("not readable JSON" in g for g in r.gaps)
    assert any("no other model is set" in n for n in r.judge_notes)


def test_an_unusable_other_model_is_named_and_the_gap_stays(tmp_path):
    rd = RunDir.create("impossible-math", base=tmp_path)
    build_mock_log(rd.logs)

    def broken(m, name):
        if name == J.DEFAULT_JUDGE_BLOCKED_MODEL:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return main

    main = _model(_reviews_stopped)

    async def go():
        saved = J._resolve_models, J._resolve_fallback
        J._resolve_models = lambda m, judge_model=None: J._Models(main, main, main, main)
        J._resolve_fallback = broken
        try:
            return await J._judge_async(rd, None, engine="two-pass")
        finally:
            J._resolve_models, J._resolve_fallback = saved

    (r,) = anyio.run(go)
    assert not r.fully_assessed and any(FILTERED_TEXT in g for g in r.gaps)
    assert any("could not be used (OPENAI_API_KEY is not set)" in n for n in r.judge_notes)

    # the replay takes the same path: the other model is unavailable there too
    saved = tmp_path / "saved.jsonl"
    saved.write_text((rd.root / J.JUDGE_CALLS_FILE).read_text())
    (again,) = judge_run(rd, replay=saved, engine="two-pass")
    assert again.headline == r.headline and again.gaps == r.gaps
    assert any("could not be used (OPENAI_API_KEY is not set)" in n for n in again.judge_notes)
