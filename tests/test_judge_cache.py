"""Prompt caching: one warming call per transcript before the fan-out, byte-identical
transcript prefixes across scanners, and the cache-read share in the report."""

from __future__ import annotations

import time

import anyio
from inspect_ai.model import ChatMessageAssistant, ChatMessageUser, ModelOutput, ModelUsage, get_model

import swarmbench.judge.scanners as S
from swarmbench.judge import mock_answer
from swarmbench.judge.budget import cache_read_share
from swarmbench.judge.extract import AgentView, SampleInputs


def _inputs(n=3):
    agents = [
        AgentView(name=f"agent-{i}", messages=[ChatMessageUser(content="go"),
                                               ChatMessageAssistant(content=f"work of agent-{i}")])
        for i in range(1, n + 1)
    ]
    return SampleInputs(
        scenario="s", run_id="r", sample_id=1, epoch=1, agents=agents, foreign=[], agents_meta=[],
        messages=[{"id": 1, "sender": "agent-1", "to": "all", "text": "team note"}], monitor_flags=[],
        bridge_summary={}, bridge_uses=[], protected_hashes={}, problems=[], agent_usage={}, outcome="",
    )


class Recorder:
    def __init__(self, delay=0.03):
        self.delay = delay
        self.calls: list[dict] = []

    def model(self):
        async def outputs(input, tools, tool_choice, config):
            blocks = input[-1].content if isinstance(input[-1].content, list) else [input[-1]]
            prefix, question = blocks[0].text, (blocks[1].text if len(blocks) > 1 else "")
            who = next((f"agent-{i}" for i in range(1, 9) if f"work of agent-{i}" in prefix), "team")
            call = {"who": who, "prefix": prefix, "question": question, "start": time.perf_counter(),
                    "cache_prompt": config.cache_prompt}
            self.calls.append(call)
            await anyio.sleep(self.delay)
            call["end"] = time.perf_counter()
            return ModelOutput.from_content("mockllm/model", mock_answer(prefix + question))

        return get_model("mockllm/model", custom_outputs=outputs)


def _run(recorder):
    async def go():
        limiter = S.make_limiter(8)
        model = recorder.model()
        async with anyio.create_task_group() as tg:
            tg.start_soon(S.run_agent_scanners, _inputs(), model, None, None, None, limiter)
            tg.start_soon(S.run_team_scanners, _inputs(), model, None, None, None, limiter)

    anyio.run(go)


def test_one_warming_call_per_transcript_before_the_fan_out():
    rec = Recorder()
    _run(rec)
    for who in ("agent-1", "agent-2", "agent-3", "team"):
        calls = sorted((c for c in rec.calls if c["who"] == who), key=lambda c: c["start"])
        assert len(calls) > 1
        first, rest = calls[0], calls[1:]
        assert all(c["start"] >= first["end"] for c in rest), f"{who}: fan-out started before the warm call ended"
    # different transcripts warm at the same time, not one after another
    firsts = [min((c for c in rec.calls if c["who"] == w), key=lambda c: c["start"]) for w in ("agent-1", "agent-2")]
    assert firsts[1]["start"] < firsts[0]["end"]


def test_prefixes_are_byte_identical_and_cached():
    rec = Recorder(delay=0.0)
    _run(rec)
    for who in ("agent-1", "agent-2", "agent-3", "team"):
        calls = [c for c in rec.calls if c["who"] == who]
        assert len({c["prefix"] for c in calls}) == 1, f"{who}: transcript prefix differs between scanners"
        assert len({c["question"] for c in calls}) == len(calls)  # the question comes after, and varies
        assert all(c["cache_prompt"] for c in calls)
    # the transcript is in the prefix, the scanner question is not
    c = rec.calls[0]
    assert "[BEGIN TRANSCRIPT]" in c["prefix"] and "Rate how far it went" not in c["prefix"]
    assert "Rate how far it went" in c["question"]


def test_cache_read_share():
    usage = {
        "anthropic/claude-sonnet-5-5": ModelUsage(input_tokens=1000, output_tokens=100,
                                                   input_tokens_cache_read=8000, input_tokens_cache_write=1000),
        "anthropic/claude-opus-5-5": ModelUsage(input_tokens=500, output_tokens=50),
    }
    share, reads, total = cache_read_share(usage)
    assert reads == 8000 and total == 10500 and abs(share - 8000 / 10500) < 1e-9
    assert cache_read_share({}) == (None, 0, 0)


def test_judge_cost_line_shows_the_cache_share(tmp_path):
    from swarmbench.judge import judge_run
    from swarmbench.paths import RunDir
    from tests.fixtures import build_mock_log

    rd = RunDir.create("demo", base=tmp_path)
    build_mock_log(rd.logs)
    (report,) = judge_run(rd, model="mockllm/model")
    assert report.stats["judge_cache_read_share"] == 0.0  # the mock model doesn't cache
    assert "read from the prompt cache" in rd.report_md.read_text()
