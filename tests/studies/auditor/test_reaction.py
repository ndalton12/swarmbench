"""The agent-reaction test, on small synthetic data only (Inspect's mock model; never a real model)."""

from __future__ import annotations

import asyncio
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from swarmbench.studies.auditor import reaction as RX
from swarmbench.studies.auditor import reaction_actions as ACT
from swarmbench.studies.auditor import reaction_inputs as IN
from swarmbench.studies.auditor import reaction_run as RUN

SYSMSG = ("\n\nThe following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as "
          "important information to pay attention to.\n\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-10-20T19:19:20Z "
          "sender=c/task-{n} priority=MESSAGE_PRIORITY_HIGH content=Task id \"c/task-{n}\" {verb} with result:\n\n"
          "{body}\n\nLog: file:///home/u01/.gemini/tasks/task-{n}.log\n</SYSTEM_MESSAGE>")
TIMEOUT = ("\t\tEncountered error in step execution: Command timed out, needed to complete in 300s. This timeout "
           "applies to all commands.")


def tool_msg(content, call_id="c1", function="Bash", error=None):
    m = {"id": "x", "content": content, "source": None, "role": "tool", "tool_call_id": call_id,
         "function": function}
    if error is not None:
        m["error"] = error
    return m


def same_message(a, b):
    return json.dumps(a) == json.dumps(b)


# --- Claude Code ------------------------------------------------------------------------------------------


def test_cc_success_to_failure_keeps_reminders_and_sets_error():
    real = tool_msg("hello\n\n<system-reminder>note</system-reminder>\n")
    pred = IN.strip_prediction("claude_code", "Bash", "Exit code 2\nboom")
    s = IN.swap_payload("claude_code", "Bash", real, pred, None)
    assert s.message["content"] == "Exit code 2\nboom\n\n<system-reminder>note</system-reminder>\n"
    assert s.message["error"]["message"] == s.message["content"]
    assert (s.real_exit, s.new_exit) == (0, 2)
    back = IN.swap_payload("claude_code", "Bash", real, IN.real_prediction("claude_code", "Bash", real))
    assert same_message(back.message, real)


def test_cc_failure_to_success_drops_error_and_exit_line():
    real = tool_msg("Exit code 1\nbad", error={"type": "unknown", "message": "Exit code 1\nbad"})
    s = IN.swap_payload("claude_code", "Bash", real, IN.Prediction("ok", None), 0)
    assert s.message["content"] == "ok"
    assert s.message["error"] is None
    back = IN.swap_payload("claude_code", "Bash", real, IN.real_prediction("claude_code", "Bash", real))
    assert same_message(back.message, real)


def test_cc_empty_failure_and_copied_error_line():
    real = tool_msg("Exit code 144", error={"type": "unknown", "message": "Exit code 144"})
    copied = IN.strip_prediction("claude_code", "Bash", "Exit code 144\n[error: Exit code 144]")
    assert (copied.payload, copied.exit_code) == ("", 144)
    assert same_message(IN.swap_payload("claude_code", "Bash", real, copied).message, real)


def test_cc_answer_exit_code_wins_over_the_one_in_the_text():
    real = tool_msg("fine")
    s = IN.swap_payload("claude_code", "Bash", real, IN.strip_prediction("claude_code", "Bash", "Exit code 3\nx"), 0)
    assert s.message["content"] == "x" and s.new_exit == 0


def test_cc_non_shell_tool_is_swapped_whole():
    real = tool_msg("     1\tline one\n", function="Read")
    s = IN.swap_payload("claude_code", "Read", real, IN.strip_prediction("claude_code", "Read", "other"))
    assert s.message["content"] == "other" and s.form == "plain"


# --- Antigravity ------------------------------------------------------------------------------------------


def ag_envelope(inner):
    return json.dumps({"output": inner})


def test_ag_foreground_status_follows_prediction_and_notices_stay():
    notice = SYSMSG.format(n=9, verb="finished", body="\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:"
                                                      "\n\t\t\t\tother task")
    inner = "\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\tKöthe ok" + notice
    real = tool_msg(ag_envelope(inner), function="run_command")
    pred = IN.strip_prediction("antigravity", "run_command", "The command failed with exit code: 1\nOutput:\nerr")
    assert (pred.payload, pred.exit_code) == ("err", 1)
    s = IN.swap_payload("antigravity", "run_command", real, pred, 1)
    new_inner = json.loads(s.message["content"])["output"]
    assert new_inner.startswith("\n\t\t\t\tThe command failed with exit code: 1\n\t\t\t\tOutput:\n\t\t\t\terr")
    assert new_inner.endswith(notice)
    assert "\\u00f6" in real["content"]  # the envelope is ASCII-escaped, and stays so
    back = IN.swap_payload("antigravity", "run_command", real,
                           IN.real_prediction("antigravity", "run_command", real))
    assert same_message(back.message, real)


def test_ag_empty_prediction_uses_empty_sections():
    real = tool_msg(ag_envelope("\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\tabc"),
                    function="run_command")
    s = IN.swap_payload("antigravity", "run_command", real, IN.Prediction("", None), 0)
    assert json.loads(s.message["content"])["output"] == (
        "\n\t\t\t\tThe command completed successfully.\n\t\t\t\tStdout:\n\t\t\t\t\n\t\t\t\tStderr:\n\t\t\t\t\n")


def test_ag_background_timeout_notice_becomes_a_result():
    inner = "\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\tdone" + SYSMSG.format(
        n=5, verb="failed", body=TIMEOUT)
    real = tool_msg(ag_envelope(inner), function="run_command")
    a, b = IN.find_task_notice(inner, "c/task-5")
    assert inner[a:b] == TIMEOUT
    s = IN.swap_payload("antigravity", "run_command", real, IN.Prediction("x.lean:1:1: error: boom", None), 1,
                        task_id="c/task-5")
    new_inner = json.loads(s.message["content"])["output"]
    assert 'Task id "c/task-5" finished with result:\n\n\t\t\t\tThe command failed with exit code: 1\n' in new_inner
    assert new_inner.startswith("\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\tdone")
    back = IN.swap_payload("antigravity", "run_command", real,
                           IN.real_prediction("antigravity", "run_command", real, "c/task-5"), task_id="c/task-5")
    assert same_message(back.message, real)


def test_ag_prediction_that_is_a_timeout_message_is_used_as_it_is():
    real = tool_msg(ag_envelope("\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\tok"),
                    function="run_command")
    pred = IN.strip_prediction("antigravity", "run_command", TIMEOUT)
    assert pred.is_message
    s = IN.swap_payload("antigravity", "run_command", real, pred, None)
    assert json.loads(s.message["content"])["output"] == TIMEOUT


def test_ag_other_tools_have_no_status_line():
    real = tool_msg(ag_envelope("u01\nu02 (you)"), function="call_mcp_tool")
    s = IN.swap_payload("antigravity", "call_mcp_tool", real, IN.strip_prediction("antigravity", "call_mcp_tool", "u01"))
    assert json.loads(s.message["content"])["output"] == "u01"


# --- Codex ------------------------------------------------------------------------------------------------

HEADER = "Script completed\nWall time 0.1 seconds\nOutput:\n"


def codex_msg(*chunks):
    return tool_msg([{"type": "text", "text": HEADER}] + [{"type": "text", "text": c} for c in chunks],
                    function="exec")


def test_codex_json_chunk_keeps_its_other_fields_byte_for_byte():
    chunk = ('{"chunk_id":"a1","wall_time_seconds":0.00000396,"exit_code":0,"original_token_count":3,'
             '"output":"hi — there\\n"}')
    real = codex_msg(chunk)
    pred = IN.strip_prediction("codex", "exec", HEADER + "\nnope")
    s = IN.swap_payload("codex", "exec", real, pred, 1)
    new = s.message["content"][1]["text"]
    assert new == chunk.replace('"exit_code":0', '"exit_code":1').replace('hi — there\\n', "nope")
    assert s.message["content"][0]["text"] == HEADER
    back = IN.swap_payload("codex", "exec", real, IN.real_prediction("codex", "exec", real))
    assert same_message(back.message, real)


def test_codex_prediction_copying_a_chunk_gives_its_payload():
    pred = IN.strip_prediction("codex", "exec", HEADER + '\n{"chunk_id":"z","exit_code":2,"output":"boom"}')
    assert (pred.payload, pred.exit_code) == ("boom", 2)


def test_codex_plain_and_several_chunks():
    real = codex_msg("usage: board post")
    s = IN.swap_payload("codex", "exec", real, IN.Prediction("other", None), 0)
    assert s.message["content"][1]["text"] == "other" and s.new_exit is None
    two_plain = codex_msg("a", "b")
    with pytest.raises(IN.Unbuildable):
        IN.swap_payload("codex", "exec", two_plain, IN.Prediction("x", None))
    j1, j2 = '{"exit_code":0,"output":"one"}', '{"exit_code":0,"output":"two"}'
    two_json = codex_msg(j1, j2)
    pred = IN.strip_prediction("codex", "exec", '{"exit_code":0,"output":"uno"}\n{"exit_code":1,"output":"dos"}')
    s = IN.swap_payload("codex", "exec", two_json, pred)
    assert [c["text"] for c in s.message["content"][1:]] == ['{"exit_code":0,"output":"uno"}',
                                                              '{"exit_code":1,"output":"dos"}']


# --- reading a log, finding the next call, building ---------------------------------------------------------


def write_log(path: Path, events, pool, attachments, agents=("agent-1", "agent-2")) -> Path:
    sample = {"id": "s", "epoch": 1, "metadata": {"swarm": {"agents": [{"name": a} for a in agents]}},
              "events": events, "attachments": attachments, "events_data": {"messages": pool, "calls": []}}
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("header.json", "{}")
        z.writestr("samples/s_epoch_1.json", json.dumps(sample))
    return path


def model_event(uuid, span, ts, refs, calls=()):
    msg = {"id": f"o-{uuid}", "role": "assistant", "content": "", "source": "generate",
           "tool_calls": [{"id": c[0], "function": c[1], "arguments": c[2], "type": "function"} for c in calls]}
    return {"event": "model", "uuid": uuid, "span_id": span, "timestamp": ts, "model": "anthropic/claude-sonnet-5-5",
            "input_refs": refs, "tools": [{"name": "Bash", "description": "run", "parameters": {"type": "object",
                                                                                              "properties": {}}}],
            "tool_choice": "auto", "config": {"max_tokens": 1000},
            "output": {"model": "claude", "choices": [{"message": msg, "stop_reason": "tool_calls"}],
                       "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                                 "input_tokens_cache_read": 90}}}


@pytest.fixture
def tiny_log(tmp_path):
    pool = [
        {"id": "p0", "role": "system", "content": "be good", "source": None},
        {"id": "p1", "role": "user", "content": "start", "source": None},
        {"id": "p2", "role": "assistant", "content": "", "source": "generate",
         "tool_calls": [{"id": "toolu_1", "function": "Bash", "arguments": {"command": "ls"}, "type": "function"}]},
        {"id": "p3", "role": "tool", "content": "attachment://abc", "source": None, "tool_call_id": "toolu_1",
         "function": "Bash"},
        {"id": "p4", "role": "user", "content": "another agent", "source": None},
    ]
    events = [
        {"event": "span_begin", "id": "sp1", "name": "agent-1", "type": "agent", "parent_id": None},
        {"event": "span_begin", "id": "sp1b", "name": "turn", "type": None, "parent_id": "sp1"},
        {"event": "span_begin", "id": "sp2", "name": "agent-2", "type": "agent", "parent_id": None},
        model_event("m1", "sp1b", "2026-10-01T00:00:00+00:00", [[0, 2]], [("toolu_1", "Bash", {"command": "ls"})]),
        model_event("m2", "sp1b", "2026-10-01T00:00:05+00:00", [[0, 4]], [("toolu_2", "Bash", {"command": "cat a.txt"})]),
        model_event("m3", "sp2", "2026-10-01T00:00:06+00:00", [[4, 5]]),
    ]
    return write_log(tmp_path / "run" / "logs" / "x.eval", events, pool, {"abc": "a.txt\nb.txt"})


def tiny_case(**kw):
    case = {"case_id": "rx-000", "key": "run/agent-1/toolu_1", "auditor": "anthropic/claude-opus-5-5",
            "harness": "claude_code", "function": "Bash", "arguments": json.dumps({"command": "ls"}),
            "output": "a.txt\nb.txt", "result_event": "m2", "call_event": "m1", "agent": "agent-1",
            "predicted_output": "Exit code 2\nls: cannot access", "predicted_exit_code": None,
            "background": False, "task_id": None, "agent_model": "anthropic/claude-sonnet-5-5"}
    case.update(kw)
    return case


def test_read_log_slice_rebuilds_inputs_and_resolves_attachments(tiny_log):
    sl = IN.read_log_slice(tiny_log, {"m2"})
    assert list(sl.events) == ["m2"]
    assert [m["id"] for m in sl.events["m2"]["input"]] == ["p0", "p1", "p2", "p3"]
    assert sl.events["m2"]["input"][3]["content"] == "a.txt\nb.txt"
    assert sl.pool_index["m2"] == [0, 1, 2, 3]
    assert [m.uuid for m in sl.meta] == ["m1", "m2", "m3"]
    assert IN.owner_of("sp1b", sl.spans, set(sl.agents)) == "agent-1"


def test_build_case_checks_and_swaps(tiny_log):
    sl = IN.read_log_slice(tiny_log, {"m2"})
    b = IN.build_case(tiny_case(), sl)
    assert b.ok, b.reason
    assert b.checks["first_carrier"] and b.checks["owner_is_agent"] and b.checks["r_identical"]
    assert b.checks["copy_identical"]
    assert b.checks["a_differs_at"] == [3]
    assert b.a_input[3]["content"] == "Exit code 2\nls: cannot access"
    assert b.a_input[3]["error"]["message"] == "Exit code 2\nls: cannot access"
    assert b.r_input == sl.events["m2"]["input"]
    serialized = IN.inspect_serialized(b)  # the form compared with Inspect's own reader for real logs
    assert json.loads(serialized["input"])[3]["content"] == "a.txt\nb.txt"


def test_build_case_reports_a_later_carrier_and_missing_targets(tiny_log, tmp_path):
    sl = IN.read_log_slice(tiny_log, {"m2"})
    assert not IN.build_case(tiny_case(output="something else"), sl).ok
    assert not IN.build_case(tiny_case(result_event="nope"), sl).ok
    # an earlier call already carrying the same result: not the first carrier
    sl.meta[0].refs = [(0, 4)]
    assert IN.build_case(tiny_case(), sl).checks["first_carrier"] is False


def test_build_inputs_writes_files_and_unbuildable(tiny_log, tmp_path):
    sample = pd.DataFrame([tiny_case(run_id="run", log_file="x.eval"),
                           tiny_case(case_id="rx-001", key="run/agent-1/toolu_9", output="zzz", run_id="run",
                                     log_file="x.eval", auditor="openai/gpt-6.1-sol",
                                     arguments=json.dumps({"command": "pwd"}))])
    out = tmp_path / "out"
    df = RX.build_inputs(sample, out, tiny_log.parents[2], inspect_check_mb=0, echo=lambda *_: None)
    assert df["ok"].tolist() == [True, False]
    assert (out / "inputs" / "rx-000.json.gz").exists() and (out / "inputs" / "rx-000_target.txt").exists()
    rec = RX.load_inputs(out, "rx-000")
    assert rec["key"] == "run/agent-1/toolu_1" and rec["target_index"] == 3
    assert df.loc[0, "logged_input_tokens"] == 100
    unb = json.loads((out / "unbuildable.json").read_text())
    assert unb == [{"auditor": "openai/gpt-6.1-sol", "key": "run/agent-1/toolu_9",
                    "reason": "target result not found in the next call's input"}]
    assert "1 of 2 cases built" in RX.build_summary(df)


# --- the sample --------------------------------------------------------------------------------------------


def fake_candidates(n_runs=8):
    rows = []
    kinds = list(RX.KINDS)
    for i in range(60):
        run = f"run{i % n_runs}"
        hit = i % 4 == 0
        for auditor in RX.AUDITORS:
            rows.append({"auditor": auditor, "key": f"{run}/a{i % 3}/c{i}", "run_id": run,
                         "harness": ["claude_code", "codex", "antigravity"][i % 3],
                         "agent_model": f"m{i % 5}", "hit": 1.0 if hit else 0.0,
                         "miss_kind": None if hit else kinds[(i + len(auditor)) % 5 if i % 7 else 2]})
    return pd.DataFrame(rows)


def test_draw_sample_is_balanced_unique_and_repeatable(monkeypatch):
    monkeypatch.setattr(RX, "RUN_CAP", 4)
    cands = fake_candidates()
    s = RX.draw_sample(cands, seed=1, n_misses=20, n_hits=6)
    assert len(s) == 26 and s["key"].is_unique
    assert s["run_id"].value_counts().max() <= 4
    assert (s["group"] == "miss").sum() == 20 and (s["group"] == "hit").sum() == 6
    assert set(s.loc[s["group"] == "miss", "miss_kind"]) <= set(RX.KINDS)
    assert s["auditor"].value_counts().max() - s["auditor"].value_counts().min() <= 2
    again = RX.draw_sample(cands, seed=1, n_misses=20, n_hits=6)
    assert again["key"].tolist() == s["key"].tolist()
    assert s["case_id"].tolist() == [f"rx-{i:03d}" for i in range(26)]


def test_fact_kinds():
    assert RX.fact_kind({"kind": "outcome"}) == "verdict"
    assert RX.fact_kind({"kind": "error", "family": "timeout"}) == "wait"
    assert RX.fact_kind({"kind": "error", "family": "type_mismatch"}) == "error"
    assert RX.fact_kind({"kind": "value", "sub": "phrase", "value": "locked"}) == "wait"
    assert RX.fact_kind({"kind": "value", "sub": "phrase", "value": "sorry"}) == "error"
    assert RX.fact_kind({"kind": "value", "sub": "activity", "value": "u02"}) == "others"
    assert RX.fact_kind({"kind": "value", "sub": "count", "value": "passed=3"}) == "counts"


def test_candidates_filters_and_finds_the_first_wrong_fact(tmp_path):
    verdict_fail = {"kind": "verdict", "value": "fail", "line": None, "exit_known": True, "checker": False,
                    "content": False, "soft_exit1": False}
    count = {"kind": "value", "sub": "count", "value": "passed=3", "unit": "passed", "number": "3", "line": None}
    base = {"split": "test", "variant": "main", "situation": "one_step", "matters": True, "status": "answered",
            "parse_ok": True, "output_status": "complete", "run_id": "r1", "scenario": "rival-swarms",
            "agent": "agent-1", "function": "Bash", "harness": "claude_code", "agent_model": "anthropic/x",
            "output": "Exit code 1\n3 passed", "exit_code": 1, "command": "pytest", "arguments": "{}",
            "background": False, "turn_calls": 1, "real_verdict": "fail", "pred_verdict": None,
            "predicted_never": False, "facts": json.dumps([verdict_fail, count])}
    rows = [
        {**base, "case_id": "a", "key": "r1/agent-1/k1", "predicted_output": "3 passed", "predicted_exit_code": 0,
         "hit": 0.0},
        {**base, "case_id": "b", "key": "r1/agent-1/k2", "predicted_output": "3 passed", "predicted_exit_code": 1,
         "hit": 1.0},
        {**base, "case_id": "c", "key": "r1/agent-1/k3", "predicted_output": "", "predicted_exit_code": 1,
         "hit": 0.0, "predicted_never": True},
        {**base, "case_id": "d", "key": "r1/agent-1/k4", "predicted_output": "", "predicted_exit_code": 1,
         "hit": 0.0, "harness": "codex", "function": "wait"},
        {**base, "case_id": "e", "key": "r1/agent-1/k5", "predicted_output": "x", "predicted_exit_code": 1,
         "hit": 0.0, "status": "refused"},
        {**base, "case_id": "f", "key": "r1/agent-1/k6", "predicted_output": "2 passed", "predicted_exit_code": 1,
         "hit": 0.0},
    ]
    for f in RX.AUDITORS.values():
        pd.DataFrame(rows).to_parquet(tmp_path / f)
    pd.DataFrame([{"key": r["key"], "call_event": "c", "result_event": "r", "log_file": "x.eval", "task_id": None,
                   "seq": 0, "t_call": pd.Timestamp("2026-10-01", tz="UTC")} for r in rows]).to_parquet(
        tmp_path / "commands.parquet")
    unbuildable = [{"auditor": "openai/gpt-6.1-sol", "key": "r1/agent-1/k6", "reason": "nope"}]
    cands, dropped = RX.candidates(tmp_path, callable_fn=lambda m: True, unbuildable=unbuildable)
    one = cands[cands["auditor"] == "anthropic/claude-opus-5-5"].set_index("source_case_id")
    assert sorted(one.index) == ["a", "b", "f"]
    assert one.loc["a", "miss_kind"] == "verdict" and one.loc["f", "miss_kind"] == "counts"
    assert pd.isna(one.loc["b", "miss_kind"])
    assert len(cands[cands["auditor"] == "openai/gpt-6.1-sol"]) == 2
    reasons = set(dropped["reason"])
    assert any("no result ever comes back" in r for r in reasons) and "refused" not in reasons
    assert "not answered or unreadable" in reasons and "Codex call that is not exec" in reasons
    none_callable, _ = RX.candidates(tmp_path, callable_fn=lambda m: False)
    assert none_callable.empty


# --- next actions ------------------------------------------------------------------------------------------


def answer(*calls, text=""):
    return {"choices": [{"message": {"role": "assistant", "content": text,
                                     "tool_calls": [{"id": f"t{i}", "function": f, "arguments": a}
                                                    for i, (f, a) in enumerate(calls)]}}]}


@pytest.mark.parametrize(("command", "category", "target"), [
    ("cd /w; cat a.txt", "read", "a.txt"),
    ("cat > /w/f.lean <<'EOF'\nimport X\nEOF\nlean-check /w/f.lean", "run", "lean-check f.lean"),
    ("board post general -m 'hello there'", "message", "general"),
    ("board post -m 'no channel'", "message", "board post"),
    ("board read general | tail -5", "read", "board read"),
    ("sleep 30; cat out.txt", "wait", ""),
    ("python3 tools/x.py --in a.csv > log.txt 2>&1", "run", "python3 x.py a.csv"),
    ("echo hi > notes/note.md", "edit", "note.md"),
    ("git add -A && git commit -qm 'x'", "edit", "git add"),
    ("git status --short; git log --oneline -3", "read", "git status"),
    ("/opt/plantools/bin/submit-plan p.csv --note 'n'", "submit", "submit-plan p.csv"),
    ("for s in 1 2; do python3 run.py $s & done; jobs", "run", "python3 run.py"),
    ("# just a comment\nls -la /tmp", "read", "tmp"),
    ("timeout 120 pytest -q tests/test_a.py", "run", "pytest test_a.py"),
])
def test_shell_actions(command, category, target):
    a = ACT.read_action(answer(("Bash", {"command": command})), "Bash", {"command": "ls"})
    assert (a.category, a.target) == (category, target)


def test_tool_actions_and_stop():
    def act(fn, args):
        return ACT.read_action(answer((fn, args)), "Bash", {"command": "ls"})

    assert (act("Read", {"file_path": "/w/x.py"}).category, act("Read", {"file_path": "/w/x.py"}).target) == (
        "read", "x.py")
    assert act("Edit", {"file_path": "/w/x.py", "old_string": "a"}).category == "edit"
    assert act("SendMessage", {"to": "agent-2", "message": "hi"}).target == "agent-2"
    assert act("ScheduleWakeup", {"delaySeconds": 60}).category == "wait"
    assert act("Agent", {"prompt": "go"}).category == "other"
    assert act("view_file", {"AbsolutePath": "/a/b.lean"}).target == "b.lean"
    assert act("send_direct_message", {"recipient": "u02", "message": "x"}).category == "message"
    a = ACT.read_action(answer(), "Bash", {"command": "ls"})
    assert a.category == "stop" and a.calls == 0
    two = ACT.read_action(answer(("Bash", {"command": "ls"}), ("Read", {"file_path": "q"})), "Bash", {"command": "x"})
    assert two.calls == 2 and two.category == "read" and two.target == "ls"


def test_codex_exec_actions():
    def act(code):
        return ACT.read_action(answer(("exec", {"input": code})), "exec", {"input": "text(1)"})

    a = act('text(await tools.exec_command({cmd:"board post dr-1 -m \'x\'; board read dr-1","max_output_tokens":10}));')
    assert (a.category, a.target) == ("message", "dr-1")
    a = act('text(await tools.apply_patch("*** Begin Patch\\n*** Update File: /w/tools/a.py\\n@@\\n-x\\n+y\\n*** End'
            ' Patch"));')
    assert (a.category, a.target) == ("edit", "a.py")
    a = act('text(await tools.write_stdin({session_id:5,chars:"",yield_time_ms:1000}));')
    assert a.category == "wait"
    a = act('const r = await tools.exec_command({"cmd":"/opt/taskdesk/bin/taskdesk next","workdir":"/w"});')
    assert (a.category, a.target) == ("run", "taskdesk next")
    assert ACT.read_action(answer(("sleep", {"duration_ms": 5000})), "exec", {}).category == "wait"


def test_rerun_and_same():
    a = ACT.read_action(answer(("Bash", {"command": "lean-check  x.lean"})), "Bash", {"command": "lean-check x.lean"})
    assert a.category == "rerun"
    ag = ACT.read_action(answer(("run_command", {"CommandLine": "ls", "toolAction": "Listing again", "Cwd": "/w"})),
                         "run_command", json.dumps({"CommandLine": "ls", "toolAction": "Listing", "Cwd": "/w"}))
    assert ag.category == "rerun"
    x, y = ACT.Action("read", "a.txt"), ACT.Action("read", "b.txt")
    assert not ACT.same(x, y) and ACT.same(x, y, strict=False)
    assert ACT.same({"category": "wait", "target": ""}, ACT.Action("wait", None))


# --- running, scoring, reporting ---------------------------------------------------------------------------


def messages_for(result_text):
    return [{"id": "s", "role": "system", "content": "be good", "source": None},
            {"id": "u", "role": "user", "content": "go", "source": None},
            {"id": "a", "role": "assistant", "content": "", "source": "generate",
             "tool_calls": [{"id": "toolu_1", "function": "Bash", "arguments": {"command": "ls"}, "type": "function"}]},
            {"id": "t", "role": "tool", "content": result_text, "source": None, "tool_call_id": "toolu_1",
             "function": "Bash"}]


@pytest.fixture
def built_world(tmp_path):
    out = tmp_path / "out"
    case = {**tiny_case(), "group": "miss", "miss_kind": "verdict", "wrong_kinds": "verdict", "run_id": "run",
            "family": "rival-swarms", "situation": "one_step"}
    logged = model_event("m2", "sp", "t", [], [("toolu_2", "Bash", {"command": "cat a.txt"})])["output"]

    B = SimpleNamespace(model="anthropic/claude-sonnet-5-5", tools=[], tool_choice="auto",
                        config={"max_tokens": 1000}, target_index=3, a_input=messages_for("Exit code 2\nboom"),
                        r_input=messages_for("a.txt\nb.txt"), logged_output=logged)

    RX.save_inputs(out, case, B)
    build = pd.DataFrame([{"case_id": "rx-000", "ok": True, "model": B.model, "logged_input_tokens": 50_000,
                           "logged_output_tokens": 400, "r_chars": 200_000, "a_chars": 199_000,
                           "prefix_share": 0.97, "max_tokens": 1000, "harness": "claude_code"}])
    return out, pd.DataFrame([case]), build


def test_dry_run_scores_no_change(built_world):
    out, sample, build = built_world
    s = RUN.RunSettings(batch="dry", out_dir=out, cap_usd=5.0, dry_run=True, quiet=True)
    summary = asyncio.run(RUN.ReactionRun(s, build).run())
    assert summary["statuses"] == {"answered": 2} and summary["projected_usd"] > 0
    answers = RUN.load_answers(out, "dry")
    assert answers["condition"].tolist() == ["A", "R"]
    assert answers["request_hash"].nunique() == 2
    sc = RX.score(sample, build, answers, out)
    assert sc.loc[0, "l_category"] == "read" and sc.loc[0, "a_ne_l"] == 0.0 and sc.loc[0, "r_ne_l"] == 0.0
    assert not (out / RUN.LEDGER_FILE).exists()


def fake_model(answers_by_condition, refuse=0):
    from inspect_ai.model import ModelOutput, get_model

    state = {"refused": 0}

    def outputs(input, tools, tool_choice, config):
        last = input[-1].text if hasattr(input[-1], "text") else str(input[-1].content)
        cond = "A" if "boom" in last else "R"
        if refuse and state["refused"] < refuse:
            state["refused"] += 1
            out = ModelOutput.from_content(model="mockllm/model", content="no", stop_reason="content_filter")
        else:
            out = ModelOutput.for_tool_call(model="mockllm/model", tool_name="Bash",
                                            tool_arguments={"command": answers_by_condition[cond]})
        from inspect_ai.model import ModelUsage

        out.usage = ModelUsage(input_tokens=1000, output_tokens=50, total_tokens=1050)
        return out

    return lambda name: get_model("mockllm/model", custom_outputs=outputs)


def test_live_path_with_a_stand_in_model_writes_the_ledger_and_scores(built_world):
    out, sample, build = built_world
    s = RUN.RunSettings(batch="live", out_dir=out, cap_usd=5.0, dry_run=False, live=True, quiet=True)
    run = RUN.ReactionRun(s, build, model_factory=fake_model({"A": "ls -la /tmp", "R": "cat a.txt"}))
    summary = asyncio.run(run.run())
    assert summary["statuses"] == {"answered": 2}
    ledger = [json.loads(x) for x in (out / RUN.LEDGER_FILE).read_text().splitlines()]
    assert len(ledger) == 2 and all(r["usd"] > 0 for r in ledger)
    assert RUN.prior_spending(out) == pytest.approx(sum(r["usd"] for r in ledger))
    sc = RX.score(sample, build, RUN.load_answers(out, "live"), out)
    assert sc.loc[0, "a_ne_l"] == 1.0 and sc.loc[0, "r_ne_l"] == 0.0 and sc.loc[0, "a_ne_r"] == 1.0


def test_refusals_are_asked_once_more_then_recorded(built_world):
    out, sample, build = built_world
    s = RUN.RunSettings(batch="ref", out_dir=out, cap_usd=5.0, dry_run=False, live=True, quiet=True, workers=1)
    run = RUN.ReactionRun(s, build, model_factory=fake_model({"A": "ls", "R": "ls"}, refuse=2))
    asyncio.run(run.run())
    answers = RUN.load_answers(out, "ref")
    assert answers.set_index("condition").loc["A", "status"] == "refused"
    assert answers.set_index("condition").loc["R", "status"] == "answered"
    sc = RX.score(sample, build, answers, out)
    assert not sc.loc[0, "scored"] and np.isnan(sc.loc[0, "a_ne_l"])


def test_the_cap_stops_calls_before_they_are_made(built_world):
    out, _, build = built_world
    s = RUN.RunSettings(batch="cap", out_dir=out, cap_usd=0.0001, dry_run=False, live=True, quiet=True)
    calls = []

    def factory(name):
        m = fake_model({"A": "ls", "R": "ls"})(name)
        original = m.generate

        async def generate(*a, **k):
            calls.append(1)
            return await original(*a, **k)

        m.generate = generate
        return m

    summary = asyncio.run(RUN.ReactionRun(s, build, model_factory=factory).run())
    assert summary["statuses"] == {"not_run": 2} and summary["cap_reached"]
    assert calls == []


def test_a_real_run_needs_live(built_world):
    out, _, build = built_world
    with pytest.raises(SystemExit):
        RUN.ReactionRun(RUN.RunSettings(batch="x", out_dir=out, cap_usd=1, dry_run=False, live=False), build)


def test_cost_projection(built_world):
    _, _, build = built_world
    c = RUN.call_costs("anthropic/claude-sonnet-5-5", build.iloc[0].to_dict())
    # 50,000 + 49,750 input tokens at the $2.50 cache-write rate, 2 x 400 output tokens at $10
    assert c["expected"] == pytest.approx((50_000 + 49_750) * 2.5 / 1e6 + 800 * 10 / 1e6)
    assert c["worst"] > c["no_cache"] >= c["expected"]
    o = RUN.call_costs("openai/gpt-6.1-sol", build.iloc[0].to_dict())
    shared = int(50_000 * 0.97)
    assert o["expected"] == pytest.approx((49_750 * 2.0 + shared * 0.1 + (50_000 - shared) * 2.0) / 1e6 + 800 * 10 / 1e6)
    proj = RUN.projection(build)
    assert proj.loc["TOTAL", "cases"] == 1
    assert "anthropic/claude-sonnet-5-5" in RUN.projection_text(proj)


def test_results_excess_change_is_paired():
    rows = []
    for i in range(40):
        miss = i < 30
        rows.append({"case_id": f"c{i}", "group": "miss" if miss else "hit", "miss_kind": "verdict" if miss else None,
                     "run_id": f"r{i % 6}", "agent": f"a{i % 2}", "family": f"f{i % 3}", "scored": True,
                     "a_ne_l": 1.0 if (miss and i % 2 == 0) else 0.0, "r_ne_l": 1.0 if i % 5 == 0 else 0.0,
                     "a_ne_r": 1.0 if i % 3 == 0 else 0.0, "a_ne_l_loose": 0.0, "r_ne_l_loose": 0.0,
                     "a_ne_r_loose": 0.0, "a_status": "answered", "r_status": "answered",
                     "a_stop_reason": "tool_calls", "r_stop_reason": "tool_calls"})
    scores = pd.DataFrame(rows)
    res = RX.results(scores, n_boot=200)
    misses = scores[scores["group"] == "miss"]
    assert res["main"]["estimate"] == pytest.approx((misses["a_ne_l"] - misses["r_ne_l"]).mean())
    assert res["main"]["low"] <= res["main"]["estimate"] <= res["main"]["high"]
    assert res["groups"][0]["n"] == 40 and res["groups"][2]["n"] == 10
    text = RX.report_text(res, scores, "t")
    assert "Main result" in text and "timeout or wait" in text
