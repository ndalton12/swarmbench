"""The auditor study's commands table (swarmbench.studies.auditor.extract). No model calls."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from inspect_ai.event import ModelEvent, SpanBeginEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageTool,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
)
from inspect_ai.tool import ToolCall

from swarmbench.studies.auditor import extract as ex

DATA = Path(__file__).resolve().parents[2] / "data"
T0 = datetime(2026, 10, 23, 7, 0, 0, tzinfo=UTC)

# --- output parsing -------------------------------------------------------------------------

NOTICE = (
    "[Message] timestamp=2026-10-23T07:00:31Z sender=conv/task-5 priority=MESSAGE_PRIORITY_HIGH "
    'content=Task id "conv/task-5" finished with result:\n\n\t\t\t\tThe command failed with exit code: 1\n'
    "\t\t\t\tOutput:\n\t\t\t\terror: boom\n\n\nLog: file:///home/u01/.gemini/x/task-5.log\n"
)
SYS = (
    "\n\nThe following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system "
    f"as important information to pay attention to.\n\n<SYSTEM_MESSAGE>\n{NOTICE}</SYSTEM_MESSAGE>"
)
LS_OUT = "\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\ta.lean\n"
BG_OUT = (
    "Tool is running as a background task with task id: conv/task-5\nTask Description: lean-check a.lean\n"
    "Task logs are available at: file:///home/u01/.gemini/x/task-5.log"
)


def test_envelope_and_system_messages():
    wrapped = json.dumps({"output": LS_OUT + SYS})
    text = ex.unwrap_envelope(wrapped)
    own, blocks = ex.split_system_messages(text)
    assert own == LS_OUT
    assert len(blocks) == 1
    notice = ex.parse_task_done(blocks[0])
    assert notice.task_id == "conv/task-5" and notice.verb == "finished"
    assert notice.finished_at == datetime(2026, 10, 23, 7, 0, 31, tzinfo=UTC)
    assert notice.output.strip().endswith("error: boom")
    assert "Log: file://" not in notice.output
    assert ex.unwrap_envelope('{"output": "x", "other": 1}') == '{"output": "x", "other": 1}'
    assert ex.unwrap_envelope("plain") == "plain"


def test_background_ids_wall_time_and_exit_codes():
    assert ex.background_task_id(BG_OUT) == "conv/task-5"
    assert ex.background_task_id(LS_OUT) is None
    assert ex.codex_wall_time("Script completed\nWall time 0.4 seconds\nOutput:\n\nhi") == 0.4
    assert ex.codex_wall_time("Exit code: 0\nWall time: 12.5 seconds\nOutput:\n") == 12.5
    assert ex.codex_wall_time("no timing here") is None
    assert ex.exit_code("antigravity", "run_command", LS_OUT) == 0
    assert ex.exit_code("antigravity", "run_command", "The command failed with exit code: 127\n") == 127
    assert ex.exit_code("antigravity", "view_file", LS_OUT) is None
    assert ex.exit_code("claude_code", "Bash", "Error: Exit code 2\nboom") == 2
    assert ex.exit_code("claude_code", "Bash", "fine", is_error=False) == 0
    assert ex.exit_code("claude_code", "Bash", "fine") == 0
    assert ex.exit_code("claude_code", "Bash", "fine", is_error=True) is None
    assert ex.exit_code("claude_code", "Bash", "Command did not complete within 120s") is None
    assert ex.exit_code("codex", "exec", 'Script completed\n{"exit_code":3,"output":"x"}') == 3
    assert ex.exit_code("codex", "exec", '{"exit_code":0}{"exit_code":1}') is None
    assert ex.exit_code("codex", "exec", None) is None


def test_truncation_markers_and_mock_models():
    assert ex.is_truncated("\t\t\t\t<truncated 41 lines>\nstructure")
    assert ex.is_truncated("a\n…120 tokens truncated…\nb")
    assert not ex.is_truncated("all fine")
    assert ex.is_mock_model("mockllm/model") and ex.is_mock_model(None)
    assert not ex.is_mock_model("openrouter/google/gemini-3.1-pro-preview")


def test_claude_code_notices_reminders_and_codex_sessions():
    out = (
        "Exit code 7\n\n<system-reminder>\n[SYSTEM NOTIFICATION]\n<task-notification>\n<task-id>bw93</task-id>\n"
        "<tool-use-id>toolu_9</tool-use-id>\n<output-file>/tmp/x.output</output-file>\n<status>completed</status>\n"
        '<summary>Background command "sleep 5" completed (exit code 0)</summary>\n</task-notification>\n'
        "</system-reminder>"
    )
    assert ex.strip_reminders(out) == "Exit code 7"
    assert ex.strip_reminders("plain\n") == "plain\n"
    (n,) = ex.parse_cc_notices(out)
    assert (n.task_id, n.tool_use_id, n.status) == ("bw93", "toolu_9", "completed")
    assert (
        ex.cc_background_id("Command running in background with ID: boztkf5vo. Output is being written")
        == "boztkf5vo"
    )
    assert ex.cc_background_id("hello") is None
    assert ex.codex_session(
        'Script completed\n{"wall_time_seconds":30.5,"session_id":31047,"output":""}'
    ) == ("session:31047", True)
    assert ex.codex_session('{"session_id":31047,"exit_code":0,"output":"done"}') == ("session:31047", False)
    assert ex.codex_session('{"exit_code":0}') == (None, False)


def test_claude_code_stream_times():
    use = {
        "type": "assistant",
        "timestamp": "2026-10-20T22:06:46.484Z",
        "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]},
    }
    res = {
        "type": "user",
        "timestamp": "2026-10-20T22:06:46.497Z",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1", "is_error": False}]},
    }
    st = ex.parse_stream_lines([json.dumps(use), "not json {", json.dumps(res)])
    assert (st.result["toolu_1"] - st.use["toolu_1"]).total_seconds() == pytest.approx(0.013)
    assert st.is_error["toolu_1"] is False


# --- a whole Antigravity run, built by hand ---------------------------------------------------


def _model(t: float, inputs: list, calls: list[ToolCall] | None, text: str = "") -> ModelEvent:
    out = ModelOutput.from_message(ChatMessageAssistant(content=text, tool_calls=calls or None))
    return ModelEvent(
        model="openrouter/google/gemini-3.1-pro-preview",
        input=inputs,
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=out,
        timestamp=T0 + timedelta(seconds=t),
        completed=T0 + timedelta(seconds=t + 2),
        span_id="s1",
    )


def _antigravity_sample() -> EvalSample:
    c1 = ToolCall(
        id="call_1", function="run_command", arguments={"CommandLine": "lean-check a.lean", "Cwd": "/w"}
    )
    c2 = ToolCall(id="call_2", function="run_command", arguments={"CommandLine": "ls", "Cwd": "/w"})
    c3 = ToolCall(
        id="call_3", function="run_command", arguments={"CommandLine": "lean-check b.lean", "Cwd": "/w"}
    )
    user = ChatMessageUser(content="Prove things.")
    a1 = ChatMessageAssistant(content="", tool_calls=[c1])
    r1 = ChatMessageTool(
        content=json.dumps({"output": BG_OUT}), tool_call_id="call_1", function="run_command"
    )
    a2 = ChatMessageAssistant(content="", tool_calls=[c2])
    r2 = ChatMessageTool(
        content=json.dumps({"output": LS_OUT + SYS}), tool_call_id="call_2", function="run_command"
    )
    a3 = ChatMessageAssistant(content="", tool_calls=[c3])
    r3 = ChatMessageTool(
        content=json.dumps({"output": BG_OUT.replace("task-5", "task-6")}),
        tool_call_id="call_3",
        function="run_command",
    )
    # a later call with a rewritten context re-sends the first call: the same command, not a new one
    c1_again = ToolCall(
        id="call_1", function="run_command", arguments={"Cwd": "/w", "CommandLine": "lean-check a.lean"}
    )
    events = [
        SpanBeginEvent(id="s1", name="agent-1", type="agent", timestamp=T0),
        _model(0, [user], [c1]),
        _model(8, [user, a1, r1], [c2]),
        _model(40, [user, a1, r1, a2, r2], [c3]),
        _model(50, [user, a1, r1, a2, r2, a3, r3], None, "waiting"),
        _model(
            60,
            [
                ChatMessageUser(content="Summary so far."),
                ChatMessageAssistant(content="", tool_calls=[c1_again]),
                r1,
            ],
            None,
            "still waiting",
        ),
    ]
    meta = {
        "swarm": {
            "scenario": "proof-conference",
            "agents": [
                {
                    "name": "agent-1",
                    "harness": "antigravity",
                    "model": "openrouter/google/gemini-3.1-pro-preview",
                    "uid": 2001,
                    "user": "u01",
                    "sandbox": "team-swarm",
                }
            ],
        }
    }
    return EvalSample(id=1, epoch=1, input="x", target="", events=events, metadata=meta)


def test_antigravity_background_join(tmp_path):
    rows = ex.extract_run("r1", tmp_path, tmp_path / "x.eval", _antigravity_sample())
    assert [r["key"] for r in rows] == ["r1/agent-1/call_1", "r1/agent-1/call_2", "r1/agent-1/call_3"]
    bg, ls, lost = rows
    assert bg["background"] and bg["task_id"] == "conv/task-5"
    assert bg["output_status"] == "complete" and "error: boom" in bg["output"] and bg["exit_code"] == 1
    assert bg["timing_source"] == "async_done"
    assert bg["t_call"] == T0 + timedelta(seconds=2)
    assert bg["t_result"] == datetime(2026, 10, 23, 7, 0, 31, 500000, tzinfo=UTC)
    assert bg["duration_s"] == pytest.approx(29.5)
    assert bg["t_seen"] == T0 + timedelta(seconds=40)  # the request that carried the notice
    assert ls["output"] == LS_OUT and "SYSTEM_MESSAGE" not in ls["output"]
    assert ls["timing_source"] == "next_request" and ls["duration_s"] == pytest.approx(30)
    assert ls["exit_code"] == 0 and not ls["background"]
    assert lost["background"] and lost["output_status"] == "missing" and lost["output"] is None
    assert lost["duration_s"] is None and lost["timing_source"] is None
    assert [r["seq"] for r in rows] == [0, 1, 2]
    assert rows[0]["command"] == "lean-check a.lean"
    assert json.loads(rows[0]["arguments"])["Cwd"] == "/w"
    df = ex.to_frame(rows)
    assert list(df.columns) == ex.COLUMNS


# --- the real-run fixtures --------------------------------------------------------------------


@pytest.fixture(scope="module")
def real():
    run_dir = DATA / "realrun"
    log = next((run_dir / "logs").glob("*.eval"))
    sample = ex.read_sample(log)
    return run_dir, log, sample, ex.extract_run("realrun", run_dir, log, sample)


def test_mock_runs_are_not_real():
    run_dir = DATA / "monitor_fp"  # a test run whose agents use Inspect's mockllm
    log = next((run_dir / "logs").glob("*.eval"))
    inv = ex.inventory_row("monitor_fp", run_dir, log, ex.read_sample(log))
    assert not inv["real"] and inv["agent_models"] == "mockllm/model"


def test_real_fixture_inventory_and_rows(real):
    run_dir, log, sample, rows = real
    inv = ex.inventory_row(run_dir.name, run_dir, log, sample)
    assert inv["real"] and inv["harnesses"] == "claude_code"
    df = ex.to_frame(rows)
    assert len(df) > 20 and df["key"].is_unique
    # one row per tool call a model really made (re-sent context is never counted again)
    made = sum(
        len(e.output.message.tool_calls or [])
        for e in sample.events
        if e.event == "model" and e.output and e.output.choices
    )
    assert len(df) == made
    assert set(df["output_status"]) <= {"complete", "truncated", "missing"}
    assert (df["output_status"] != "missing").mean() > 0.9
    for _, g in df.groupby("agent"):
        assert g["seq"].tolist() == list(range(len(g)))
    timed = df.dropna(subset=["duration_s"])
    assert (timed["duration_s"] >= 0).all() and len(timed) > 0.9 * len(df)
    assert set(timed["timing_source"]) <= {"harness_stream", "next_request"}
    assert (
        df.loc[df["output_status"] != "missing", "t_seen"]
        >= df.loc[df["output_status"] != "missing", "t_call"]
    ).all()
