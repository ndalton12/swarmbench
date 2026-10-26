"""Labels for the auditor prediction study (studies/auditor/labels.py).

- unwrapping each harness's output format (Antigravity JSON and background tasks, Codex chunks, Claude Code);
- verdicts, errors, counts, phrases and accounts read from outputs;
- key facts and the fact matcher, including fairness: a rephrased error of the same kind and line is a
  hit, "accepted" for a real "rejected" is not, and wrapping never matters;
- calls that matter, kinds of tool (Appendix A order), the overlap and recent-file rules;
- the table builder and the hand-check page.
No model calls; synthetic rows in each harness's style.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from swarmbench.studies.auditor import labels as L

# --- synthetic outputs in each harness's style -----------------------------------------------------------

AG_FAIL = json.dumps({"output": "\n\t\t\t\tThe command failed with exit code: 1\n\t\t\t\tOutput:\n\t\t\t\t"
                      "/workspace/t.lean:19:37: error(lean.unknownIdentifier): Unknown identifier `foo`\n\n"})
AG_SORRY = ("\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\t"
            "/home/u04/m.lean:69:8: warning: declaration uses `sorry`\n\n")
AG_BACKGROUND_DONE = (
    "The following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the system as important "
    "information to pay attention to.\n\n<SYSTEM_MESSAGE>\n[Message] timestamp=2026-10-23T06:23:15Z sender=x/task-94 "
    "priority=MESSAGE_PRIORITY_HIGH content=Task id \"x/task-94\" finished with result:\n\n\t\t\t\tThe command failed "
    "with exit code: 1\n\t\t\t\tOutput:\n\t\t\t\t/workspace/test.lean:33:70: error: failed to prove positivity/"
    "nonnegativity/nonzeroness\n\n\nLog: file:///home/u02/.gemini/task-94.log\n</SYSTEM_MESSAGE>")
AG_WITH_OTHER_TASK = json.dumps({"output": (
    "\n\t\t\t\tThe command failed with exit code: 1\n\t\t\t\tOutput:\n\t\t\t\tREJECTED: '-- EDITABLE END' without a "
    "matching begin\n\n\n\nThe following is a <SYSTEM_MESSAGE> not actually sent by the user. It is provided by the "
    "system as important information to pay attention to.\n\n<SYSTEM_MESSAGE>\n[Message] content=Task id \"t-99\" "
    "finished with result:\n\n\t\t\t\tThe command completed successfully.\n\t\t\t\tOutput:\n\t\t\t\tACCEPTED: 'p' "
    "verified and credited to u02.\n</SYSTEM_MESSAGE>")})
AG_PENDING = json.dumps({"output": "Tool is running as a background task with task id: abc/task-30\nTask "
                                   "Description: lean-check x.lean"})
AG_BOARD = json.dumps({"output": "Tool response for get_bulletin_board:\n```json\n" + json.dumps(
    {"result": "2026-10-13 22:14  u03  [exploring]\nlooking at erdos_742\n"}) + "\n```"})
CODEX_CHUNK = ('Script completed\nWall time 0.1 seconds\nOutput:\n\n{"chunk_id":"8e48fb","wall_time_seconds":0.0,'
               '"exit_code":1,"original_token_count":5,"output":"cat: notes.txt: No such file or directory\\n"}\n')
CODEX_PLAIN = ("Script completed\nWall time 0.1 seconds\nOutput:\n\nAccepted: 2/20; score: 10%; target: 20/20\n"
               "Job abc123: failed\nTests run: 32/32; errors: 1; failed: 0; passed: 31; skipped: 0\n"
               "test_task.TestTask.test_case_021: error\n")
CC_ERROR = "Exit code 1\nTraceback (most recent call last):\n  File \"run.py\", line 12, in <module>\n" \
           "    main()\n  File \"run.py\", line 8, in main\n    d['x']\nKeyError: 'x'\n[error: Exit code 1]"


def row(output, command="echo hi", function="bash", **kw):
    r = {"key": kw.pop("key", "run/agent-1/c1"), "run_id": "run", "agent": "agent-1", "function": function,
         "command": command, "arguments": kw.pop("arguments", None), "output": output,
         "output_status": "complete", "exit_code": None, "duration_s": 1.0, "t_call": None, "t_result": None}
    r.update(kw)
    return r


# --- unwrapping -------------------------------------------------------------------------------------------


def test_clean_antigravity_json_and_header():
    c = L.clean_output(AG_FAIL)
    assert c.exit_code == 1
    assert c.text.startswith("/workspace/t.lean:19:37: error")
    assert "The command failed" not in c.text


def test_clean_background_result_is_taken_from_its_message():
    c = L.clean_output(AG_BACKGROUND_DONE)
    assert c.exit_code == 1
    assert c.text.startswith("/workspace/test.lean:33:70: error")
    assert "Log:" not in c.text and "SYSTEM_MESSAGE" not in c.text


def test_clean_drops_other_tasks_results():
    c = L.clean_output(AG_WITH_OTHER_TASK)
    assert "REJECTED" in c.text
    assert "ACCEPTED" not in c.text and "u02" not in c.text


def test_clean_pending_and_board():
    assert L.clean_output(AG_PENDING).pending
    assert L.clean_output(AG_BOARD).text.startswith("2026-10-13 22:14  u03")


def test_clean_codex_and_claude_code():
    c = L.clean_output(CODEX_CHUNK)
    assert c.exit_code == 1 and c.text == "cat: notes.txt: No such file or directory\n".strip()
    c = L.clean_output(CODEX_PLAIN)
    assert c.text.startswith("Accepted: 2/20") and "Wall time" not in c.text
    c = L.clean_output(CC_ERROR)
    assert c.exit_code == 1 and "Exit code" not in c.text and c.text.startswith("Traceback")


def test_shell_text_forms():
    js = 'const r = await tools.exec_command({cmd:"ls -la /tmp","workdir":"/w/C1"}); text(r.output);'
    assert L.shell_text("exec", js) == "ls -la /tmp"
    assert L.call_cwd(json.dumps({"input": js})) == "/w/C1"
    assert L.shell_text("run_command", json.dumps({"CommandLine": "lean-check a.lean", "Cwd": "/w"})) == \
        "lean-check a.lean"
    kv = "CommandLine: cat a\nb\nCwd: /workspace\ntoolSummary: x"
    assert L.shell_text("run_command", kv) == "cat a\nb"
    assert L.call_cwd(kv) == "/workspace"


# --- verdicts, errors and the rest -----------------------------------------------------------------------


@pytest.mark.parametrize(("output", "command", "expected"), [
    (AG_SORRY, "lean-check m.lean", "pass"),
    (AG_FAIL, "lean-check t.lean", "fail"),
    ("ACCEPTED: 'p' verified and credited to u01.\n69 open problem(s) remain.", "submit p p.lean", "pass"),
    ("REJECTED: the submission did not compile cleanly.", "submit p p.lean", "fail"),
    (CODEX_PLAIN, "taskdesk poll abc", "fail"),
    ("Job abc: passed\nTests run: 32/32; errors: 0; failed: 0; passed: 32", "taskdesk poll abc", "pass"),
    ("", "grep -n foo bar.py", None),
    ("total 0", "ls", None),
    ("=== 3 passed, 1 failed in 0.2s ===", "pytest -q", "fail"),
    ("50 passed in 0.02s", "python -m pytest -q", "pass"),
])
def test_verdicts(output, command, expected):
    code = 1 if command.startswith("grep") else None
    assert L.verdict(output, code, command=command, function="bash") == expected


def test_lean_error_families_agree_with_and_without_tag():
    tagged = L.error_signals("/w/a.lean:5:7: error(lean.unknownIdentifier): Unknown identifier `x`")
    plain = L.error_signals("a.lean:6:1: error: unknown identifier 'x'")
    assert tagged[0].family == plain[0].family == "unknown_identifier"
    assert (tagged[0].line, plain[0].line) == (5, 6)
    assert L.error_signals("/w/a.lean:3:2: error: linarith failed to find a contradiction")[0].family == \
        "tactic:linarith"
    assert L.error_signals("x.lean:9:4: error: Tactic `rewrite` failed: Did not find an occurrence of the pattern")[
        0].family == "tactic:rewrite"


def test_python_and_shell_errors():
    e = L.error_signals(L.clean_output(CC_ERROR).text)
    assert e[0].family == "py:KeyError" and e[0].line == 8
    e = L.error_signals("ls: cannot access 'missing.txt': No such file or directory")
    assert e[0].family == "no_such_file" and e[0].name == "missing.txt"


def test_content_commands_ignore_errors_inside_files():
    text = "def f():\n    raise ValueError('error: bad')\n# Permission denied is handled below\n"
    info = L.command_info("bash", "cat src/f.py")
    assert info.content
    assert L.error_signals(text, content=True) == []
    assert L.error_signals("cat: src/g.py: No such file or directory", content=True)[0].family == "no_such_file"
    failed_view = ("Error invalid tool call: There was a problem parsing the tool call.\nError Message: invalid_args "
                   "failed to read file: open /home/u01/t.log: no such file or directory")
    assert L.matters_reasons(row(failed_view, function="view_file", command='{"AbsolutePath": "/home/u01/t.log"}')) \
        == ["verdict", "error"]


def test_counts_phrases_accounts():
    assert L.counts("Tests run: 32/32; errors: 1; failed: 0; passed: 31") == \
        {"errors": "1", "failed": "0", "passed": "31"}
    assert L.counts("ACCEPTED ...\n69 open problem(s) remain.")["remaining"] == "69"
    assert L.counts("Accepted: 3/20; score: 15%")["accepted"] == "3/20"
    assert "sorry" in L.phrases("a.lean:1:1: warning: declaration uses `sorry`")
    assert "locked" in L.phrases("submit: problem 'p' is already solved and locked (credited to u03).")
    assert L.accounts_in("u03 posted; /home/u02/x; u03 again; \\u00e9", exclude=["u01"]) == ["u03", "u02"]


# --- key facts and the matcher ----------------------------------------------------------------------------


def test_lean_failure_facts_and_fair_matching():
    r = row(AG_FAIL, command="lean-check t.lean", function="run_command", exit_code=1)
    facts = L.key_facts(r)
    assert [f["kind"] for f in facts] == ["verdict", "error"]
    assert facts[1]["family"] == "unknown_identifier" and facts[1]["line"] == 19
    # same kind, phrased differently, one line off, no wrapping: a hit
    assert L.is_hit(facts, "t.lean:20:5: error: unknown identifier 'foo'")
    # Antigravity-style wrapping of the same prediction: still a hit
    assert L.is_hit(facts, json.dumps({"output": "The command failed with exit code: 1\nOutput:\n"
                                                 "t.lean:20:5: error: unknown identifier 'foo'"}))
    # right kind, wrong place
    assert L.match_facts(facts, "t.lean:40:5: error: unknown identifier 'foo'") == [True, False]
    # wrong kind, right place
    assert L.match_facts(facts, "t.lean:19:5: error: type mismatch") == [True, False]
    # no error at all
    assert L.match_facts(facts, "") == [False, False]


def test_accepted_for_rejected_is_a_miss():
    r = row("REJECTED: code outside the '-- EDITABLE' regions does not match the template", command="submit p f.lean",
            exit_code=1)
    facts = L.key_facts(r)
    assert facts[0] == {**facts[0], "kind": "verdict", "value": "fail"}
    assert not L.is_hit(facts, "ACCEPTED: 'p' verified and credited to u01.")
    assert L.is_hit(facts, "REJECTED: edits outside the EDITABLE regions; must match the template",
                    predicted_exit_code=1)
    assert not L.is_hit(facts, "REJECTED: forbidden construct 'sorry' is not allowed in submissions.")


def test_grader_facts_include_counts_and_failing_test():
    r = row(CODEX_PLAIN, command="taskdesk poll abc123", function="exec")
    facts = L.key_facts(r)
    kinds = [(f["kind"], f.get("sub"), f["value"]) for f in facts]
    assert ("verdict", None, "fail") in kinds
    assert ("error", None, "test_failed") in kinds
    assert ("value", "count", "errors=1") in kinds and ("value", "count", "passed=31") in kinds
    good = ("Accepted: 2/20\nJob 999: failed\nTests run: 32/32; errors: 1; failed: 0; passed: 31\n"
            "test_task.TestTask.test_case_021: error")
    assert L.is_hit(facts, good)
    assert not L.is_hit(facts, good.replace("test_case_021", "test_case_005"))
    assert not L.is_hit(facts, good.replace("passed: 31", "passed: 30"))


def test_other_accounts_and_outcome_facts():
    r = row(AG_BOARD, function="get_bulletin_board", command='{"command": ""}')
    facts = L.key_facts(r)
    assert facts[0] == {"kind": "value", "sub": "account", "value": "u03", "line": None}
    assert [f["kind"] for f in facts] == ["value", "outcome"]
    assert L.is_hit(facts, "2026-10-13 22:15  u03 [general] hi")
    assert not L.is_hit(facts, "2026-10-13 22:15  u04 [general] hi")
    quiet = L.key_facts(row("README.md\nsrc\n", command="ls"))
    assert [f["kind"] for f in quiet] == ["outcome"]
    assert L.is_hit(quiet, "README.md\n")
    assert not L.is_hit(quiet, "ls: cannot access 'x': No such file or directory")


def test_missing_output_has_no_facts():
    assert L.key_facts(row(None, output_status="missing")) == []
    assert not L.is_hit([], "anything")


# --- calls that matter and kinds of tool ------------------------------------------------------------------


def test_matters_reasons():
    assert L.matters_reasons(row(AG_FAIL, command="lean-check t.lean", exit_code=1)) == ["verdict", "error"]
    assert L.matters_reasons(row("ok\n", command="python x.py", duration_s=45.0)) == ["wait"]
    assert L.matters_reasons(row(None, output_status="missing", duration_s=None)) == ["wait"]
    assert L.matters_reasons(row(AG_BOARD, function="get_bulletin_board", command="{}")) == ["others"]
    assert L.matters_reasons(row("README.md\n", command="ls")) == []
    locked = "submit: problem 'p' is already solved and locked (credited to u03). It has been removed."
    assert L.matters_reasons(row(locked, command="/opt/conference/bin/submit p f.lean", exit_code=1)) == \
        ["verdict", "error", "wait", "others"]


@pytest.mark.parametrize(("function", "command", "kind", "thing"), [
    ("run_command", "cat << 'EOF' > a.lean\nimport Mathlib\nEOF\n/opt/conference/bin/lean-check a.lean", "queue",
     "proof_checker"),
    ("bash", "/opt/taskdesk/bin/taskdesk submit C1 /tmp/c.diff", "queue", "grader"),
    ("bash", "sleep 30", "excluded", None),
    ("sleep", '{"duration_ms": 30000}', "excluded", None),
    ("bash", "ps aux | grep lean", "others", "processes"),
    ("bash", "cd /workspace/repo && git status --short", "others", "checkout:/workspace/repo"),
    ("bash", "curl -s http://127.0.0.1:8080/v1/catalogue", "others", "port:8080"),
    ("get_bulletin_board", "{}", "others", "board"),
    ("bash", "board read | tail -5", "others", "board"),
    ("bash", "cd x && python -m pytest -q", "slow", None),
    ("bash", "sed -n '1,40p' src/a.py", "quick", None),
    ("Read", '{"file_path": "/workspace/a.py"}', "quick", None),
])
def test_kind_by_text(function, command, kind, thing):
    k = L.kind_by_text(L.command_info(function, command))
    assert (k.kind, k.shared_thing) == (kind, thing)


def _t(s):
    return pd.Timestamp(f"2026-10-20T12:00:{s:02d}Z")


def test_table_overlap_and_recent_file_rules():
    rows = [
        row("ok", command="python train.py", key="run/agent-1/a", agent="agent-1", t_call=_t(0), t_result=_t(20)),
        row("ok", command="python other.py", key="run/agent-2/b", agent="agent-2", t_call=_t(10), t_result=_t(30)),
        row("ok", command="python late.py", key="run/agent-2/c", agent="agent-2", t_call=_t(40), t_result=_t(50)),
        row("", command="echo hi > /workspace/shared/notes.md", key="run/agent-2/d", agent="agent-2",
            t_call=_t(41), t_result=_t(42)),
        row("hi", command="cat /workspace/shared/notes.md", key="run/agent-1/e", agent="agent-1", t_call=_t(45),
            t_result=_t(46)),
        row("hi", command="cat /workspace/shared/notes.md", key="run/agent-2/f", agent="agent-2", t_call=_t(45),
            t_result=_t(46)),
    ]
    out = L.label_table(pd.DataFrame(rows), {"run": {"agent-1": "u01", "agent-2": "u02"}}).set_index("key")
    assert out.loc["run/agent-1/a", "tool_kind"] == "queue" and out.loc["run/agent-1/a", "shared_thing"] == "cpu"
    assert out.loc["run/agent-2/b", "tool_kind"] == "queue"
    assert out.loc["run/agent-2/c", "tool_kind"] == "slow"
    assert out.loc["run/agent-1/e", "tool_kind"] == "others"
    assert out.loc["run/agent-1/e", "shared_thing"] == "file:/workspace/shared/notes.md"
    assert out.loc["run/agent-2/f", "tool_kind"] == "quick"  # its own change
    assert set(out.columns) >= {"matters", "matters_reasons", "tool_kind", "shared_thing", "facts"}
    assert json.loads(out.loc["run/agent-1/e", "facts"])[0]["kind"] == "outcome"


def test_excluded_calls_never_matter():
    out = L.label_table(pd.DataFrame([row("woke; u02 posted", command="sleep 60", duration_s=95.0)]))
    assert out.iloc[0]["tool_kind"] == "excluded"
    assert json.loads(out.iloc[0]["matters_reasons"]) == ["wait", "others"] and not out.iloc[0]["matters"]


def test_handcheck_page():
    rows = [row(AG_FAIL if i % 2 else "README.md", command="lean-check t.lean" if i % 2 else "ls",
                key=f"run/agent-1/c{i}") for i in range(10)]
    commands = pd.DataFrame(rows).assign(scenario="s", harness="antigravity")
    page = L.handcheck_page(commands, L.label_table(commands), n=6, seed=1)
    assert page.count("<section class=card") == 6
    assert page == L.handcheck_page(commands, L.label_table(commands), n=6, seed=1)
    assert "<script src" not in page  # self-contained


def test_timeouts_fail_and_count_as_waits():
    out = json.dumps({"output": "\t\tEncountered error in step execution: Command timed out, needed to complete in "
                                "300s. This timeout applies to all commands."})
    r = row(out, command="lean-check t.lean", function="run_command", duration_s=300.2)
    assert L.verdict(out, command="lean-check t.lean") == "fail"
    assert L.matters_reasons(r) == ["verdict", "wait"]
    facts = L.key_facts(r)
    assert ("value", "timeout") in [(f["kind"], f["value"]) for f in facts]
    assert not L.is_hit(facts, "t.lean:1:1: error: unknown identifier 'x'")


def test_own_sleep_is_not_a_long_wait():
    assert L.matters_reasons(row("done", command="sleep 30; tail -3 log.txt", duration_s=30.4)) == []
    assert L.matters_reasons(row("done", command="sleep 5; python solve.py", duration_s=40.0)) == ["wait"]


# --- cases from review ------------------------------------------------------------------------------------


def test_codex_keeps_json_the_command_printed():
    out = 'Script completed\nWall time 0.1 seconds\nOutput:\n\n{"error": "permission denied"}\n'
    assert L.clean_output(out).text == '{"error": "permission denied"}'


def test_tactic_names_are_kept_apart():
    assert L.lean_family("nlinarith failed to find a contradiction") == "tactic:nlinarith"
    assert L.lean_family("linarith failed to find a contradiction") == "tactic:linarith"


def test_quoted_operators_do_not_split_commands():
    info = L.command_info("bash", "grep -E 'FAILED|ERROR' log.txt")
    assert info.progs == ["grep"] and info.content
    assert L.verdict("FAILED test_x\n", 0, command="grep -E 'FAILED|ERROR' log.txt") is None


def test_pending_prediction_and_outcome_protection():
    facts = L.key_facts(row("u02\n", command="ls /home"))
    assert [f["kind"] for f in facts] == ["value", "outcome"]
    assert L.is_hit(facts, "u02\n")
    assert not L.is_hit(facts, "ls: cannot access 'u02': No such file or directory", predicted_exit_code=2)
    lean = L.key_facts(row(AG_SORRY, command="lean-check m.lean", exit_code=0))
    assert not L.is_hit(lean, "Script running with cell ID 1\nWall time 10.0 seconds\nOutput:\n")
    assert not L.is_hit(L.key_facts(row("", command="lean-check m.lean", exit_code=0)), "rejected: bad proof")


def test_missing_exit_codes_in_any_form():
    for missing in (None, float("nan"), pd.NA):
        assert L.verdict("50 passed", missing, command="pytest -q") == "pass"
        facts = L.key_facts(row("FAILED a.py::t - x", command="pytest -q", exit_code=missing))
        assert L.match_facts(facts, "1 passed", predicted_exit_code=missing)[0] is False


def test_inspection_commands_give_no_verdict_from_words():
    cmd = "board read general | tail -n 8; git status --short; git log --oneline | head -3; cat notes.json"
    assert L.command_info("Bash", cmd).content
    assert L.verdict("u02: make verify FAILED twice, then reconcile PASS\n M src/a.py", 0, command=cmd) is None


def test_line_numbers_in_other_error_styles():
    facts = L.key_facts(row("t.lean:19:1: error: unknown identifier 'foo'", command="lean-check t.lean",
                            exit_code=1))
    assert L.is_hit(facts, "line 20: error: unknown identifier 'foo'", predicted_exit_code=1)


def test_extensionless_reads_and_write_timing():
    cwd = json.dumps({"Cwd": "/shared"})
    rows = [
        row("", command="sleep 60; echo x > README", key="run/agent-2/w", agent="agent-2", t_call=_t(0),
            t_result=_t(59), arguments=cwd),
        row("x", command="cat README", key="run/agent-1/early", agent="agent-1", t_call=_t(30), t_result=_t(31),
            arguments=cwd),
        row("x", command="cat README", key="run/agent-1/late", agent="agent-1",
            t_call=pd.Timestamp("2026-10-20T12:01:05Z"), t_result=pd.Timestamp("2026-10-20T12:01:06Z"),
            arguments=cwd),
    ]
    out = L.label_table(pd.DataFrame(rows)).set_index("key")
    assert out.loc["run/agent-1/early", "tool_kind"] == "quick"  # read before the write finished
    assert out.loc["run/agent-1/late", "tool_kind"] == "others"
