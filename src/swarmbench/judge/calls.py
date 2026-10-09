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


def _tool_calls(m: Any) -> str:
    """The tool calls an assistant message made (names and arguments, not their ids), so two
    conversations that differ only in what was asked of a tool never share a key."""
    calls = getattr(m, "tool_calls", None) or []
    if not calls:
        return ""
    return "\n\x1f" + json.dumps([[c.function, c.arguments or {}] for c in calls], sort_keys=True, default=str)


def call_key(input: Any) -> str:
    """A stable hash of what a judge call asked (roles, text and tool calls; never ids)."""
    if isinstance(input, str):
        parts = [f"user\n{input}"]
    else:
        parts = [f"{getattr(m, 'role', '?')}\n{_text(getattr(m, 'content', ''))}{_tool_calls(m)}"
                 for m in input or []]
    return hashlib.sha256("\n\x1e\n".join(parts).encode()).hexdigest()


class ReplayedFailure(RuntimeError):
    """A judge call that failed when it was recorded fails the same way in a replay."""

    def __init__(self, message: str, error_type: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


def failure_text(exc: BaseException) -> str:
    """The same words for a failed call whether it happened live or in a replay, so everything
    built from it (coverage, prompts) is identical in both."""
    from swarmbench.judge.budget import JudgeBudgetExhausted

    if isinstance(exc, JudgeBudgetExhausted):
        return str(exc)
    kind = exc.error_type if isinstance(exc, ReplayedFailure) else type(exc).__name__
    return f"the model call failed ({kind})"


class CallRecorder:
    """Appends one record per attempt made through attached models: the full assistant message
    (text, reasoning, tool calls), the stop reason and the call's settings, or the error."""

    def __init__(self, path: Path, append: bool = False) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not append or not self.path.exists():
            self.path.write_text("")  # one recording per judging (a resumed judging adds a session)
        # every judging session starts with a marker, so a replay keeps its calls and decisions together
        self.session = 1 + sum(1 for r in _lines(self.path) if "session" in r)
        self.write({"session": self.session})

    def attach(self, models: Any) -> None:
        seen: set[int] = set()
        for role in ("scanner", "screen", "confirm", "summarizer"):
            m = getattr(models, role, None)
            if m is not None and id(m) not in seen:
                seen.add(id(m))
                self.wrap(m)

    def wrap(self, model: Any) -> None:
        # always wrap the unrecorded call, so repeated judging runs don't stack recorders
        original = getattr(model, "_swarm_unrecorded_generate", None) or model.generate
        model._swarm_unrecorded_generate = original
        recorder = self

        async def generate(input: Any, *args: Any, **kwargs: Any) -> Any:
            settings = _settings(kwargs)
            try:
                out = await original(input, *args, **kwargs)
            except Exception as exc:
                recorder.write({"key": call_key(input), "model": str(model), "error": repr(exc)[:2000],
                                "error_type": type(exc).__name__, "retryable": retryable(model, exc),
                                "settings": settings})
                raise
            record: dict[str, Any] = {
                "key": call_key(input),
                "model": str(model),
                "output": out.completion or "",
                "settings": settings,
            }
            if out.choices:
                record["message"] = out.message.model_dump(mode="json", exclude_none=True)
                record["stop_reason"] = out.stop_reason
            recorder.write(record)
            return out

        model.generate = generate

    def record_decisions(self, sample: str, decisions: dict[str, Any]) -> None:
        """The judge's own decisions for one sample (its cost plan, which model read which part,
        when the budget stopped investigation), so a replay makes the same ones."""
        self.write({"decisions": sample, "data": decisions})

    def record_refusal(self, model: Any, input: Any, message: str) -> None:
        """A call the budget refused (never sent): replayed as the same refusal."""
        self.write({"key": call_key(input), "model": str(model), "error": message,
                    "error_type": "JudgeBudgetExhausted", "refused": True})

    def write(self, record: dict[str, Any]) -> None:
        record["time"] = datetime.now(UTC).isoformat()
        with self.path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")


def _settings(kwargs: dict[str, Any]) -> dict[str, Any]:
    config = kwargs.get("config")
    out: dict[str, Any] = {}
    if config is not None and getattr(config, "max_tokens", None):
        out["max_tokens"] = config.max_tokens
    if kwargs.get("tool_choice") is not None:
        out["tool_choice"] = str(kwargs["tool_choice"])
    if kwargs.get("tools"):
        out["tools"] = [getattr(t, "name", str(t)) for t in kwargs["tools"]]
    return out


def retryable(model: Any, exc: BaseException) -> bool:
    """Would the provider retry this failure (rate limits, overload, timeouts)? Recorded with the
    failure, so a replay retries exactly when the judging did."""
    if isinstance(exc, ReplayedFailure):
        return exc.retryable
    try:
        return bool(model.should_retry(exc))
    except Exception:
        return False


def _lines(path: Path) -> list[dict[str, Any]]:
    out = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _session(path: Path, session: int | None = None) -> list[dict[str, Any]]:
    """The records of one judging session (default: the last one). A recording without session
    markers is one session."""
    sessions: list[list[dict[str, Any]]] = [[]]
    for rec in _lines(path):
        if "session" in rec and "key" not in rec:
            if sessions[-1]:
                sessions.append([])
            continue
        sessions[-1].append(rec)
    if session is None:
        return sessions[-1]
    return sessions[session - 1] if 0 < session <= len(sessions) else []


def load_records(path: Path, session: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """key -> every recorded attempt with that input, in order, within one judging session
    (default: the last; decision records left out)."""
    records: dict[str, list[dict[str, Any]]] = {}
    for rec in _session(path, session):
        if "key" in rec:
            records.setdefault(rec["key"], []).append(rec)
    return records


def load_decisions(path: Path, session: int | None = None) -> dict[str, dict[str, Any]]:
    """sample -> the judge's recorded decisions for it, in the same session as the calls."""
    out: dict[str, dict[str, Any]] = {}
    for rec in _session(path, session):
        if "decisions" in rec:
            out[str(rec["decisions"])] = rec.get("data") or {}
    return out


def load_calls(path: Path) -> dict[str, str]:
    """key -> the last successful output text."""
    out: dict[str, str] = {}
    for key, recs in load_records(path).items():
        ok = [r for r in recs if "error" not in r]
        if ok:
            out[key] = ok[-1].get("output") or ""
    return out


def replay_name(path: Path) -> str:
    """How a replayed reader is named in coverage: after the model the recording came from."""
    from collections import Counter

    models = Counter(r.get("model") for recs in load_records(path).values() for r in recs if r.get("model"))
    return f"replay of {models.most_common(1)[0][0]}" if models else "replay"


def output_from_record(record: dict[str, Any]) -> Any:
    """The recorded ModelOutput: the full message when recorded (reasoning and tool calls
    included), else the text and tool calls of an older recording."""
    from inspect_ai.model import ChatMessageAssistant, ModelOutput
    from inspect_ai.tool import ToolCall

    if record.get("message"):
        message = ChatMessageAssistant.model_validate(record["message"])
    else:
        calls = [ToolCall(id=c["id"], function=c["function"], arguments=c.get("arguments") or {})
                 for c in record.get("tool_calls") or []]
        message = ChatMessageAssistant(content=record.get("output") or "", tool_calls=calls or None,
                                       model="replay/judge")
    out = ModelOutput.from_message(message, stop_reason="tool_calls" if message.tool_calls else "stop")
    if record.get("stop_reason"):
        out.choices[0].stop_reason = record["stop_reason"]
    return out


def replay_model(path: Path, misses: list[str] | None = None) -> Any:
    """A model that answers every judge call from a recording, never calling a model.

    It replays the recording's last judging session (calls and decisions together). A resumed
    judging is replayed with ``resume`` and the run's progress file, like the original.
    Attempts with the same input are replayed in the order they were recorded, failures
    included (a recorded failure raises ReplayedFailure), so retries and coverage history
    come out the same. Once a key's attempts are used up, its last successful answer is
    reused (older recordings kept one record per input). A call that isn't in the
    recording raises ReplayMiss (and is listed in ``misses``), so a replay can't quietly
    differ from the run it reproduces.
    """
    from inspect_ai.model import get_model

    records = load_records(path)
    used: dict[str, int] = {}

    def outputs(input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
        key = call_key(input)
        attempts = records.get(key)
        if not attempts:
            if misses is not None:
                misses.append(key)
            raise ReplayMiss(f"judge call {key[:12]} is not in the recording {Path(path).name}")
        n = used.get(key, 0)
        used[key] = n + 1
        if n < len(attempts):
            record = attempts[n]
        else:
            ok = [r for r in attempts if "error" not in r]
            if not ok:
                raise ReplayMiss(f"judge call {key[:12]} has no successful answer left in {Path(path).name}")
            record = ok[-1]
        if "error" in record:
            if record.get("error_type") == "JudgeBudgetExhausted":
                from swarmbench.judge.budget import JudgeBudgetExhausted

                raise JudgeBudgetExhausted(record["error"])
            raise ReplayedFailure(record["error"][:300], str(record.get("error_type") or "Exception"),
                                  bool(record.get("retryable")))
        return output_from_record(record)

    return get_model("mockllm/model", custom_outputs=outputs)
