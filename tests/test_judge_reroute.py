"""Asking another provider after a content filter: the conversation must be one it accepts."""

from __future__ import annotations

import anyio
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ContentReasoning, ContentText, ModelOutput

from swarmbench.judge.calls import REROUTED_KEY, portable, reroute_filtered


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


def test_a_conversation_the_other_model_took_over_stays_with_it():
    calls = {"main": 0, "other": 0}

    class Model:
        name = "m"

        async def generate(self, input, *args, **kwargs):
            calls["main"] += 1
            return ModelOutput.from_content("a/m", "main answer")

    class Other:
        async def generate(self, input, *args, **kwargs):
            calls["other"] += 1
            return ModelOutput.from_content("b/o", "other answer")

    model = reroute_filtered(Model(), lambda: Other(), name="b/o")
    mine = [ChatMessageUser(content="judge this"), ChatMessageAssistant(content="looking", model="m"),
            ChatMessageUser(content="results")]  # fmt: skip
    assert anyio.run(lambda: model.generate(mine)).completion == "main answer"
    theirs = [ChatMessageUser(content="judge this"),
              ChatMessageAssistant(content=[ContentReasoning(reasoning="", signature="enc", redacted=True)],
                                   model="o", metadata={REROUTED_KEY: "b/o"}),
              ChatMessageUser(content="results")]  # fmt: skip
    out = anyio.run(lambda: model.generate(theirs))
    assert out.completion == "other answer" and calls == {"main": 1, "other": 1}
    assert out.message.metadata[REROUTED_KEY] == "b/o"  # so the round after it stays there too
