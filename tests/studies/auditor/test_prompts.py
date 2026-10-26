from __future__ import annotations

import pandas as pd
import pytest

from swarmbench.studies.auditor import cases as C
from swarmbench.studies.auditor import prompts as P
from tests.studies.auditor.runner_fixtures import (  # noqa: F401
    NoQueue,
    make_commands,
    make_run_dir,
    no_real_queue,
)


@pytest.mark.parametrize(("text", "seconds"), [
    ("12", 12.0), ("12s", 12.0), ("1.5 minutes", 90.0), ("2m30s", 150.0), ("~90 seconds", 90.0),
    ("500ms", 0.5), ("about 2 min", 120.0), ("1 hour", 3600.0), ("", None), ("unknown", None),
])
def test_parse_seconds(text, seconds):
    assert P.parse_seconds(text) == seconds


@pytest.mark.parametrize(("text", "low", "high"), [
    ("5-30", 5.0, 30.0), ("5 to 30 seconds", 5.0, 30.0), ("1-2 min", 60.0, 120.0), ("30s - 2m", 30.0, 120.0),
    ("30–10", 10.0, 30.0), ("45", 45.0, 45.0), (None, None, None),
])
def test_parse_range(text, low, high):
    assert P.parse_range(text) == (low, high)


def test_parse_answer_reads_the_fixed_format():
    raw = P.format_answer("error: unknown identifier `x`\nline 2", 4.2, 2, 10, exit_code=1, will_wait=True)
    a = P.parse_answer(raw)
    assert a.parse_ok and a.predicted_output == "error: unknown identifier `x`\nline 2"
    assert (a.predicted_exit_code, a.predicted_seconds, a.predicted_low_s, a.predicted_high_s) == (1, 4.2, 2, 10)
    assert a.will_wait is True and a.predicted_never is False


def test_parse_answer_copes_with_sloppy_answers():
    a = P.parse_answer("<OUTPUT>\nhello\n<seconds>about 3 minutes</seconds>\n<range>1 to 5 min</range>\n"
                       "<returns>No, it hangs</returns>")
    assert a.predicted_output == "hello" and a.predicted_seconds == 180 and a.predicted_never
    assert (a.predicted_low_s, a.predicted_high_s) == (60, 300)
    assert a.parse_ok
    bare = P.parse_answer("just some text")
    assert not bare.parse_ok and bare.predicted_output == "just some text"
    empty_output = P.parse_answer("<output>\n</output>\n<seconds>1</seconds>")
    assert empty_output.parse_ok and empty_output.predicted_output == ""


def test_queue_answer():
    q = P.parse_queue_answer("<typical_wait_seconds>2 min</typical_wait_seconds><waiting_in_5_min>4</waiting_in_5_min>"
                             "<waiting_in_10_min>about 6</waiting_in_10_min><hits_limit>no</hits_limit>")
    assert (q.typical_wait_s, q.waiting_5min, q.waiting_10min, q.hits_limit, q.parse_ok) == (120, 4, 6, False, True)


@pytest.fixture(scope="module")
def setup():
    commands = C.normalise_commands(make_commands())
    draw = C.draw_cases(commands, C.stub_labels(commands), seed=3, sizes=C.DrawSizes(
        one_step_matter=6, one_step_other=2, long_history=2, repeats=2, chains=2, chain_real_past=2, shared=4,
        shared_no_record=2, queue_moments=1, practice_one_step=2, practice_one_step_other=1, practice_chains=1,
        practice_shared=1), queue_tools=NoQueue)
    rows = {r.key: r for r in commands.itertuples(index=False)}
    return commands, draw.cases, rows


def test_results_not_yet_back_are_shown_as_running():
    row = pd.Series({"t_call": pd.Timestamp("2026-01-01T10:00Z"), "t_result": pd.Timestamp("2026-01-01T10:05Z"),
                     "output": "SECRET RESULT", "output_status": "complete", "duration_s": 300.0, "exit_code": 0,
                     "background": True})
    r = type("R", (), row.to_dict())
    assert "SECRET" not in P.format_result(r, pd.Timestamp("2026-01-01T10:01Z"))
    assert "SECRET" in P.format_result(r, pd.Timestamp("2026-01-01T10:06Z"))


def test_every_kind_of_case_shares_one_fixed_part(setup):
    _, cases, rows = setup
    systems = {P.build_request(c, rows, "DESC", "a").system for c in cases.to_dict("records")
               if not (c["situation"] == "chain" and c["step"])}
    assert len(systems) == 1  # one cached copy per run and version
    assert P.build_request(cases.iloc[0].to_dict(), rows, "DESC", "b").system != systems.pop()


def test_shared_question_has_the_record_and_no_record_variant_does_not(setup):
    _, cases, rows = setup
    shared = cases[(cases.situation == "shared") & (cases.split == "test")]
    main = shared[shared.variant == "main"].iloc[0].to_dict()
    with_rec = P.build_request(main, rows, "DESC", "a").turns[-1][1]
    assert "Record of the others" in with_rec and "<will_wait>" in with_rec
    nr = shared[shared.variant == "no_record"].iloc[0].to_dict()
    without = P.build_request(nr, rows, "DESC", "a").turns[-1][1]
    assert "Record of the others" not in without


def test_chain_steps_are_a_conversation_with_cache_marks(setup):
    _, cases, rows = setup
    chain = cases[(cases.situation == "chain") & (cases.variant == "main")]
    steps = chain[chain.chain_id == chain.chain_id.iloc[0]].sort_values("step").to_dict("records")
    chain_rows = [rows[s["key"]] for s in steps]
    first = P.build_request(steps[0], rows, "DESC", "a")
    assert first.cache_turns == [0]
    third = P.build_request(steps[2], rows, "DESC", "a", past_answers=["ans0", "ans1"], chain_rows=chain_rows[:3])
    roles = [r for r, _ in third.turns]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    assert third.turns[0][1] == first.turns[0][1]  # same opening, so the cache matches
    assert third.turns[1][1] == "ans0" and third.cache_turns == [2, 4]
    last = P.build_request(steps[2], rows, "DESC", "a", past_answers=["ans0", "ans1"], chain_rows=chain_rows[:3],
                           store=False)
    assert last.cache_turns == [2]
    msgs = P.to_messages(third)
    marks = sum(1 for m in msgs for c in m.content if getattr(c, "cache_breakpoint", False))
    assert marks == 3 and marks <= 4  # Anthropic allows at most four
    assert msgs[0].role == "system" and msgs[0].content[0].cache_breakpoint


def test_run_description(tmp_path):
    d = make_run_dir(tmp_path)
    text = P.run_description(d, told="## What the agents were told\nPlease prove things.")
    assert "16 processors" in text and "README.md" in text and "Please prove things." in text
    assert "problems/a.lean" in text and "notes.md" not in text  # the judge's notes are left out
    # the researchers' own fields never reach the auditor (name, description, notes)
    assert "proof-conference" not in text and "Researchers prove" not in text
    assert len(text) <= P.DESCRIPTION_CHARS + 30
    assert P.run_description(tmp_path / "missing", told="")  # a missing folder still gives something


def test_what_agents_were_told_drops_harness_text():
    harness_para = "You are a helpful harness. Follow these rules."
    runs = {
        "r1": {"agent-1": {"system": [harness_para + "\n\nYour account on hostA is u01.", "MODEL-SPECIFIC STUFF"],
                           "user": "<system-reminder>env stuff</system-reminder>\n\nPlease port the backend.",
                           "username": "u01"},
               "agent-2": {"system": [harness_para + "\n\nYour account on hostA is u02."],
                           "user": "Please port the backend.\n\nYou take Rust.", "username": "u02"}},
        "r2": {"agent-1": {"system": [harness_para], "user": "Prove things.", "username": "u01"}},
        "r3": {"agent-1": {"system": [("<identity>Antigravity rules</identity><user_system_instructions>Be rigorous."
                                       "</user_system_instructions>")], "user": "Prove more.", "username": "u01"}},
    }
    fam = {"r1": "turf", "r2": "proofs", "r3": "proofs2"}
    harness = P.harness_paragraphs(runs, fam)
    t1 = P.told_section(runs["r1"], harness)
    assert "Please port the backend." in t1 and "Your account on hostA is <user>." in t1
    assert "helpful harness" not in t1 and "MODEL-SPECIFIC" not in t1 and "env stuff" not in t1
    assert "## Told only to agent-2\nYou take Rust." in t1
    t3 = P.told_section(runs["r3"], harness)
    assert "Be rigorous." in t3 and "Antigravity rules" not in t3


def test_queue_request_lists_checks(setup):
    commands, _, _ = setup
    t = commands.loc[commands.run_id == "run-pc", "t_call"].min() + pd.Timedelta(minutes=8)
    req = P.queue_request({"run_id": "run-pc", "t_freeze": t, "slots": 3}, commands, "DESC", None)
    text = req.turns[0][1]
    assert "3 slots" in text and "lean-check" in text
    assert "<typical_wait_seconds>" in req.system


def test_output_comes_last_so_a_cut_off_answer_keeps_its_time():
    assert P.ANSWER_FORMAT.rstrip().endswith("</output>")
    assert P.format_answer("abc", 5, 1, 9).rstrip().endswith("</output>")
    cut = P.format_answer("line one\nline two\nline three", 5, 1, 9)[:-25]  # the token limit hit mid-output
    a = P.parse_answer(cut)
    assert a.parse_ok and a.predicted_seconds == 5 and a.predicted_output.startswith("line one")


def test_later_chain_steps_show_no_real_clock_time(setup):
    commands, _, _ = setup
    row = next(commands.itertuples(index=False))
    q = P.step_question(row)
    assert P._clock(row.t_call) not in q and row.command in q


def test_output_whitespace_survives_the_round_trip():
    for text in ("  x\n", "\n\nindented\n  line  ", "", " "):
        assert P.parse_answer(P.format_answer(text, 1, 1, 2)).predicted_output == text


def test_tool_settings_that_change_the_answer_are_shown():
    import json

    row = type("R", (), {"function": "run_command", "command": "pwd",
                         "arguments": json.dumps({"CommandLine": "pwd", "Cwd": "/home/u01", "toolAction": "x"})})
    text = P.format_command(row)
    assert "/home/u01" in text and "toolAction" not in text
    edit = type("R", (), {"function": "Edit", "command": '{"file_path": "a.py"}', "arguments": '{"file_path": "a.py"}'})
    assert P.format_command(edit) == '[Edit] {"file_path": "a.py"}'
