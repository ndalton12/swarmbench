"""Record every judge model call, and replay a judging run from the record.

Each call's input is hashed (roles and text only, so message ids, call order and
concurrency don't matter) and saved with the model's raw output to
``runs/<id>/judge_calls.jsonl``. A replay model answers from that file instead
of calling any model, which makes a judging run exactly repeatable for tests
and for debugging a report.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JUDGE_CALLS_FILE = "judge_calls.jsonl"


class ReplayMiss(RuntimeError):
    """A replayed judge asked something that isn't in the record."""


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(getattr(c, "text", None) or getattr(c, "reasoning", None) or "") for c in content)
    return str(content or "")


def call_key(input: Any) -> str:
    """A stable hash of what a judge call asked (roles and text only)."""
    if isinstance(input, str):
        parts = [f"user\n{input}"]
    else:
        parts = [f"{getattr(m, 'role', '?')}\n{_text(getattr(m, 'content', ''))}" for m in input or []]
    return hashlib.sha256("\n\x1e\n".join(parts).encode()).hexdigest()


class CallRecorder:
    """Appends {key, model, output, time} for every call made through attached models."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("")  # one record per judging run

    def attach(self, models: Any) -> None:
        seen: set[int] = set()
        for role in ("scanner", "screen", "confirm", "summarizer"):
            m = getattr(models, role, None)
            if m is not None and id(m) not in seen:
                seen.add(id(m))
                self._wrap(m)

    def _wrap(self, model: Any) -> None:
        # always wrap the unrecorded call, so repeated judging runs don't stack recorders
        original = getattr(model, "_swarm_unrecorded_generate", None) or model.generate
        model._swarm_unrecorded_generate = original
        recorder = self

        async def generate(input: Any, *args: Any, **kwargs: Any) -> Any:
            out = await original(input, *args, **kwargs)
            recorder.write(call_key(input), str(model), out.completion or "")
            return out

        model.generate = generate

    def write(self, key: str, model: str, output: str) -> None:
        record = {"key": key, "model": model, "output": output, "time": datetime.now(UTC).isoformat()}
        with self.path.open("a") as f:
            f.write(json.dumps(record) + "\n")


def load_calls(path: Path) -> dict[str, str]:
    """key -> recorded output (the last record wins)."""
    calls: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            calls[rec["key"]] = rec["output"]
    return calls


def replay_model(path: Path, misses: list[str] | None = None) -> Any:
    """A model that answers every judge call from a recording, never calling a model.

    A call that isn't in the recording raises ReplayMiss (and is listed in
    ``misses``), so a replay can't quietly differ from the run it reproduces.
    """
    from inspect_ai.model import ModelOutput, get_model

    calls = load_calls(path)

    def outputs(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        key = call_key(input)
        if key not in calls:
            if misses is not None:
                misses.append(key)
            raise ReplayMiss(f"judge call {key[:12]} is not in the recording {Path(path).name}")
        return ModelOutput.from_content("replay/judge", calls[key])

    return get_model("mockllm/model", custom_outputs=outputs)
