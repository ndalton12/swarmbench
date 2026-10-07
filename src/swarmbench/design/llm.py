"""A small conversation helper around Inspect's model API."""

from __future__ import annotations

from dataclasses import dataclass, field

from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    GenerateConfig,
    Model,
    get_model,
)

from swarmbench.design.errors import DesignError

DEFAULT_DESIGN_MODEL = "anthropic/claude-opus-5-5"

# No forced tool_choice (Opus 5.5 rejects it) and no reasoning_tokens (Claude 5 rejects it).
# Replies are long: a whole scenario folder.
_CONFIG = GenerateConfig(max_tokens=32_000)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def line(self, model_name: str) -> str:
        return (
            f"{self.calls} call(s) to {model_name}, "
            f"{self.input_tokens:,} input and {self.output_tokens:,} output tokens"
        )


@dataclass
class Chat:
    """One conversation with the designer model."""

    model: Model
    system: str
    usage: Usage
    messages: list[ChatMessage] = field(default_factory=list)
    cut_off: bool = False
    """Whether the last reply stopped at the output limit."""

    async def ask(self, text: str) -> str:
        self.messages.append(ChatMessageUser(content=text))
        output = await self.model.generate(
            [ChatMessageSystem(content=self.system), *self.messages], config=_CONFIG
        )
        reply = output.completion
        self.messages.append(ChatMessageAssistant(content=reply))
        self.usage.calls += 1
        if output.usage:
            self.usage.input_tokens += output.usage.input_tokens
            self.usage.output_tokens += output.usage.output_tokens
        self.cut_off = output.stop_reason == "max_tokens"
        return reply


def resolve_model(model: str | Model | None) -> Model:
    if isinstance(model, Model):
        return model
    name = model or DEFAULT_DESIGN_MODEL
    try:
        return get_model(name)
    except Exception as e:
        raise DesignError(f"could not set up the model {name}", [str(e).strip().splitlines()[-1]]) from e
