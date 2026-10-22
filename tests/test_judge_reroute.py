"""Asking another provider after a content filter: the conversation must be one it accepts."""

from __future__ import annotations

import anyio
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ContentReasoning, ContentText, ModelOutput

from swarmbench.judge.calls import portable, reroute_filtered


def _conversation():
    reply = ChatMessageAssistant(content=[
        ContentReasoning(reasoning="", signature="sig", redacted=True),
        ContentText(text="looking it up"),
    ])  # fmt: skip
    return [ChatMessageUser(content="judge this"), reply, ChatMessageUser(content="and now?")]


def test_portable_drops_reasoning_blocks_only():
    messages = _conversation()
    out = portable(messages)
    assert [c.type for c in out[1].content] == ["text"]
    assert [c.type for c in messages[1].content] == ["reasoning", "text"]  # unchanged
    assert out[0] is messages[0] and out[2] is messages[2]


def test_the_other_provider_gets_the_portable_conversation():
    seen = {}

    class Model:
        async def generate(self, input, *args, **kwargs):
            return ModelOutput.from_content("a/m", "x", stop_reason="content_filter")

    class Other:
        async def generate(self, input, *args, **kwargs):
            seen["input"] = input
            return ModelOutput.from_content("b/m", "answer")

    model = reroute_filtered(Model(), lambda: Other(), name="b/m")
    out = anyio.run(lambda: model.generate(_conversation()))
    assert out.completion == "answer"
    assert all(not isinstance(c, ContentReasoning) for m in seen["input"]
               for c in (m.content if isinstance(m.content, list) else []))  # fmt: skip
