"""Regression tests for the Codex review of the two-pass judge (stages 1 and 2).
Mock and replay only."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser, ModelOutput
from inspect_ai.tool import ToolCall

from swarmbench.judge.extract import extract_sample
from swarmbench.judge.ledger import build_ledger
from tests.fixtures import build_mock_log


def _sample(tmp_path, **kwargs):
    path = build_mock_log(tmp_path, **kwargs)
    return read_eval_log(str(path), resolve_attachments=True).samples[0]


def _model_events(sample) -> list[Any]:
    return [e for e in sample.events if e.event == "model"]


def _call(cid: str, cmd: str) -> ToolCall:
    return ToolCall(id=cid, function="bash", arguments={"cmd": cmd})


def _event(template: Any, input: list[Any], output: Any, start=None, done=None) -> Any:
    out = output if isinstance(output, ModelOutput) else ModelOutput.from_message(output)
    return template.model_copy(update={
        "uuid": uuid.uuid4().hex, "input": input, "output": out,
        "timestamp": start or template.timestamp, "completed": done or template.completed,
    })


def _replace_model_events(sample, new_by_agent: dict[str, list[Any]]) -> None:
    """Swap each agent's model event for the given sequence (same span, so same owner)."""
    events = []
    for e in sample.events:
        if e.event == "model":
            for agent, seq in list(new_by_agent.items()):
                if seq and seq[0].span_id == e.span_id:
                    events.extend(seq)
                    new_by_agent.pop(agent)
                    break
            continue
        events.append(e)
    sample.events = events


def _ledger(sample):
    return build_ledger(sample, extract_sample(sample))


# --- 4. tool-call ids are scoped to their conversation ---------------------------------------------


def test_colliding_tool_call_ids_keep_both_results(tmp_path):
    sample = _sample(tmp_path / "a", agent_texts={"agent-1": "one", "agent-2": "two"})
    t1, t2 = _model_events(sample)
    go = ChatMessageUser(content="go")
    seqs = {}
    for template, agent, result in ((t1, "agent-1", "agent-1 sees secret.txt"), (t2, "agent-2", "agent-2 sees notes.md")):
        call = ChatMessageAssistant(content="", tool_calls=[_call("toolu_same", "ls")])
        seqs[agent] = [
            _event(template, [go], call),
            _event(template, [go, call, ChatMessageTool(content=result, tool_call_id="toolu_same", function="bash")],
                   ChatMessageAssistant(content=f"{agent} done")),
        ]
    _replace_model_events(sample, seqs)
    lg = _ledger(sample)
    results = [e for e in lg.events if e.kind == "tool_result"]
    assert sorted(lg.text(e) for e in results) == ["agent-1 sees secret.txt", "agent-2 sees notes.md"]
    links = [(lk.src, lk.dst) for lk in lg.links if lk.kind == "call_result"]
    by_id = lg.by_id()
    assert len(links) == 2 and all(by_id[a].actor == by_id[b].actor for a, b in links)


def test_same_id_different_content_in_one_conversation_is_kept_as_a_conflict(tmp_path):
    sample = _sample(tmp_path / "a", agent_texts={"agent-1": "one", "agent-2": "two"})
    t1 = _model_events(sample)[0]
    go = ChatMessageUser(content="go")
    call = ChatMessageAssistant(content="", tool_calls=[_call("t1", "cat x")])
    first = ChatMessageTool(content="x is 1", tool_call_id="t1", function="bash")
    second = ChatMessageTool(content="x is 2", tool_call_id="t1", function="bash")
    seq = [
        _event(t1, [go], call),
        _event(t1, [go, call, first], ChatMessageAssistant(content="ok")),
        _event(t1, [ChatMessageUser(content="later"), call, second], ChatMessageAssistant(content="ok again")),
    ]
    _replace_model_events(sample, {"agent-1": seq})
    lg = _ledger(sample)
    results = [e for e in lg.events if e.kind == "tool_result"]
    assert [lg.text(e) for e in results] == ["x is 1", "x is 2"]
    assert results[1].meta["conflicts_with"] == results[0].id


# --- 5. rewritten history is never mistaken for re-sent context ------------------------------------


def test_rewritten_arguments_and_reasoning_are_kept(tmp_path):
    from inspect_ai.model import ContentReasoning, ContentText

    sample = _sample(tmp_path / "a", agent_texts={"agent-1": "one", "agent-2": "two"})
    t1 = _model_events(sample)[0]
    go = ChatMessageUser(content="go")
    call = ChatMessageAssistant(content=[ContentReasoning(reasoning="list the files"), ContentText(text="ok")],
                                tool_calls=[_call("t1", "ls")])
    result = ChatMessageTool(content="a.txt", tool_call_id="t1", function="bash")
    rewritten = ChatMessageAssistant(content=[ContentReasoning(reasoning="delete the logs quietly"),
                                              ContentText(text="ok")],
                                     tool_calls=[_call("t1", "rm -rf logs")])
    seq = [
        _event(t1, [go], call),
        _event(t1, [go, call, result], ChatMessageAssistant(content="done")),
        _event(t1, [go, rewritten, result], ChatMessageAssistant(content="done again")),
    ]
    _replace_model_events(sample, {"agent-1": seq})
    lg = _ledger(sample)
    texts = [lg.text(e) for e in lg.events]
    assert "cmd: rm -rf logs" in texts and "delete the logs quietly" in texts
    assert any(e.kind == "context" and "rewritten" in lg.text(e) for e in lg.events)
    assert [lg.text(e) for e in lg.events if e.kind == "tool_result"] == ["a.txt"]  # same result: once


# --- 10. outputs are placed when they completed --------------------------------------------------------


def test_overlapping_calls_appear_in_completion_order(tmp_path):
    sample = _sample(tmp_path / "a", agent_texts={"agent-1": "one", "agent-2": "two"})
    t1, t2 = _model_events(sample)
    t0 = t1.timestamp
    slow = _event(t1, [ChatMessageUser(content="go")], ChatMessageAssistant(content="agent-1 slow answer"),
                  start=t0, done=t0 + timedelta(seconds=10))
    fast = _event(t2, [ChatMessageUser(content="go")], ChatMessageAssistant(content="agent-2 fast answer"),
                  start=t0 + timedelta(seconds=1), done=t0 + timedelta(seconds=2))
    _replace_model_events(sample, {"agent-1": [slow], "agent-2": [fast]})
    lg = _ledger(sample)
    order = [lg.text(e) for e in lg.events if e.kind == "text"]
    assert order == ["agent-2 fast answer", "agent-1 slow answer"]
    assert [e.id for e in lg.events] == [f"L{i + 1:04d}" for i in range(len(lg.events))]
    assert lg.unaccounted(sample) == []
