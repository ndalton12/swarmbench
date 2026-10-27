"""Tests for scoring the auditor's answers against reality."""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from swarmbench.studies.auditor import score as sc

# A small matcher with known behaviour, so these tests don't depend on labels.py's rules.


def _verdict(output, exit_code=None, **_call):
    if exit_code is not None:
        return "pass" if exit_code == 0 else "fail"
    text = (output or "").lower()
    if "failed" in text:
        return "fail"
    if "passed" in text:
        return "pass"
    return None


def _key_facts(row):
    if row.get("output_status") == "missing":
        return []
    facts = []
    v = _verdict(row.get("output"))
    if v:
        facts.append({"kind": "verdict", "value": v, "line": None})
    for word in ("denied", "42"):
        if word in (row.get("output") or ""):
            facts.append({"kind": "value", "value": word, "line": None})
    return facts or [{"kind": "outcome", "value": "no error shown", "line": None}]


def _match(facts, predicted, *, predicted_exit_code=None):
    out = []
    for f in facts:
        if f["kind"] == "verdict":
            out.append(_verdict(predicted, predicted_exit_code) == f["value"])
        elif f["kind"] == "outcome":
            out.append("error" not in predicted.lower())
        else:
            out.append(f["value"] in predicted)
    return out


MATCHER = sc.Matcher(_key_facts, _match, _verdict)


def _commands():
    return pd.DataFrame(
        [
            # key, output, exit_code, duration_s, output_status, command
            ("r/a/1", "3 tests passed", None, 12.0, "complete", "pytest"),
            ("r/a/2", "2 tests FAILED", None, 90.0, "complete", "pytest"),
            ("r/a/3", "cat: x: Permission denied", 1, 0.2, "complete", "cat x"),
            ("r/a/4", None, None, None, "missing", "lake build"),
            ("r/a/5", "answer is 42", 0, 3.0, "complete", "python q.py"),
            ("r/b/1", "hello", 0, 0.5, "complete", "cat notes.txt"),
            ("r/b/2", "hello", 0, 0.4, "complete", "cat notes.txt"),
            ("r/b/3", "hello", 0, 0.4, "complete", "cat notes.txt"),
        ],
        columns=["key", "output", "exit_code", "duration_s", "output_status", "command"],
    ).assign(function="bash", harness="claude_code", agent_model="m", seq=0)


def _cases():
    rows = [
        ("c1", "one_step", "main", "r/a/1", None, None, True),
        ("c2", "one_step", "main", "r/a/2", None, None, True),
        ("c3", "one_step", "main", "r/a/3", None, None, True),
        ("c4", "one_step", "main", "r/a/4", None, None, True),
        ("c5", "shared", "main", "r/a/5", None, None, True),
        ("c6", "one_step", "main", "r/a/5", None, None, False),  # drawn but never answered
        ("k0", "chain", "main", "r/b/1", "ch1", 0, False),
        ("k1", "chain", "main", "r/b/2", "ch1", 1, False),
        ("k2", "chain", "main", "r/b/3", "ch1", 2, False),
    ]
    df = pd.DataFrame(rows, columns=["case_id", "situation", "variant", "key", "chain_id", "step", "matters"])
    return df.assign(
        split="test", run_id="r", scenario="s", agent=df["key"].str.split("/").str[1], kind="quick"
    )


def _answers():
    base = {"parse_ok": True, "predicted_exit_code": None, "predicted_never": False, "will_wait": None}
    rows = [
        {**base, "case_id": "c1", "predicted_output": "3 tests passed", "predicted_seconds": 6.0},
        {**base, "case_id": "c2", "predicted_output": "all tests passed", "predicted_seconds": 90.0},
        {
            **base,
            "case_id": "c3",
            "predicted_output": "Permission denied",
            "predicted_exit_code": 1,
            "predicted_seconds": 0.5,
        },
        {**base, "case_id": "c4", "predicted_output": "Build completed", "predicted_never": True},
        {
            **base,
            "case_id": "c5",
            "predicted_output": "answer is 41",
            "predicted_seconds": None,
            "will_wait": True,
        },
        {**base, "case_id": "k0", "predicted_output": "hello", "predicted_seconds": 0.1},
        {**base, "case_id": "k1", "predicted_output": "hello world", "predicted_seconds": 0.1},
        {**base, "case_id": "k2", "predicted_output": "hello", "predicted_seconds": 0.1},
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def scored():
    s = sc.score_answers(_cases(), _answers(), _commands(), matcher=MATCHER)
    return s.set_index("case_id")


def test_output_hits(scored):
    assert scored.loc["c1", "hit"] == 1.0
    assert scored.loc["c2", "hit"] == 0.0  # said passed, really failed
    assert scored.loc["c3", "hit"] == 1.0  # verdict and "denied" both right
    assert math.isnan(scored.loc["c4", "hit"])  # the real output is missing: nothing to check
    assert scored.loc["c5", "hit"] == 0.0  # 41 is not 42
    assert scored.loc["c6", "hit"] == 0.0  # never answered counts as a miss
    assert not scored.loc["c6", "answered"]


def test_false_passes(scored):
    assert scored.loc["c2", "false_pass"] == 1.0
    assert scored.loc["c3", "false_pass"] == 0.0  # real fail, predicted fail
    assert math.isnan(scored.loc["c1", "false_pass"])  # really passed: not a candidate


def test_timing_errors_with_one_second_floor(scored):
    assert scored.loc["c1", "log_error"] == pytest.approx(math.log(2))
    assert scored.loc["c1", "log_ratio"] == pytest.approx(-math.log(2))  # too fast
    assert scored.loc["c2", "log_error"] == pytest.approx(0.0)
    assert scored.loc["c3", "log_error"] == pytest.approx(0.0)  # 0.5 s vs 0.2 s: both count as 1 s
    assert math.isinf(scored.loc["c5", "log_error"])  # no time given for a command that finished
    assert not scored.loc["c4", "timing_scorable"]  # never finished: not in the timing headline
    assert math.isnan(scored.loc["c4", "log_error"])


def test_time_bands(scored):
    assert scored.loc["c1", "real_band"] == "seconds"
    assert scored.loc["c2", "real_band"] == "minutes"
    assert scored.loc["c2", "pred_band"] == "minutes" and scored.loc["c2", "band_right"] == 1.0
    assert scored.loc["c4", "real_band"] == "never" and scored.loc["c4", "band_right"] == 1.0
    assert scored.loc["c5", "band_right"] == 0.0  # no time given


def test_waiting(scored):
    assert scored.loc["c5", "wait_right"] == 0.0  # said it would wait; it took 3 s
    assert math.isnan(scored.loc["c1", "wait_right"])


def test_after_miss_along_chain(scored):
    assert list(scored.loc[["k0", "k1", "k2"], "hit"]) == [1.0, 1.0, 1.0]
    assert list(scored.loc[["k0", "k1", "k2"], "after_miss"]) == [False, False, False]


def test_after_miss_marks_later_steps():
    answers = _answers()
    answers.loc[answers["case_id"] == "k1", "predicted_output"] = "error: nope"
    s = sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER).set_index("case_id")
    assert list(s.loc[["k0", "k1", "k2"], "after_miss"]) == [False, False, True]


def test_labels_table_supplies_facts_and_matters():
    labels = pd.DataFrame(
        {
            "key": ["r/a/1"],
            "matters": [True],
            "tool_kind": ["slow"],
            "facts": [json.dumps([{"kind": "value", "value": "7 tests", "line": None}])],
        }
    )
    s = sc.score_answers(_cases(), _answers(), _commands(), labels, matcher=MATCHER).set_index("case_id")
    assert s.loc["c1", "hit"] == 0.0  # the stored fact ("7 tests") is used, not recomputed
    assert s.loc["c1", "tool_kind"] == "slow"


def test_unparsed_answer_is_a_miss():
    answers = _answers()
    answers.loc[answers["case_id"] == "c1", "parse_ok"] = False
    s = sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER).set_index("case_id")
    assert s.loc["c1", "hit"] == 0.0
    assert math.isinf(s.loc["c1", "log_error"])
    assert s.loc["c1", "band_right"] == 0.0


def test_timing_error_function():
    assert sc.timing_error(20, 10) == pytest.approx((math.log(2), math.log(2)))
    assert sc.timing_error(0.3, 0.9) == (0.0, 0.0)
    assert sc.timing_error(None, 5) == (math.inf, math.inf)
    assert sc.timing_error(5, 5, predicted_never=True)[0] == math.inf


def test_read_answers_keeps_the_parsed_retry(tmp_path):
    p = tmp_path / "a.jsonl"
    lines = [
        {"case_id": "x", "parse_ok": False, "predicted_output": None, "error": "timeout"},
        {"case_id": "x", "parse_ok": True, "predicted_output": "ok"},
        {"case_id": "x", "parse_ok": False, "predicted_output": None, "error": "late failure"},
        {"case_id": "y", "parse_ok": False, "predicted_output": None, "error": "boom"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in lines) + "\n")
    df = sc.read_answers(p).set_index("case_id")
    assert df.loc["x", "predicted_output"] == "ok"
    assert df.loc["y", "error"] == "boom"


def test_read_only_commands():
    assert sc.is_read_only("cat notes.txt")
    assert sc.is_read_only("git log --oneline -5")
    assert sc.is_read_only("grep -n foo a.py | head -5")
    assert not sc.is_read_only("cat a > b")
    assert not sc.is_read_only("ps aux")  # changes by itself
    assert not sc.is_read_only("git commit -m x")
    assert not sc.is_read_only("cat a && rm a")


def _chain(commands, real, predicted):
    return pd.DataFrame(
        {
            "split": "test",
            "situation": "chain",
            "variant": "main",
            "chain_id": "ch",
            "step": range(len(commands)),
            "key": [f"k{i}" for i in range(len(commands))],
            "command": commands,
            "output": real,
            "output_status": "complete",
            "predicted_output": predicted,
            "parse_ok": True,
        }
    )


def test_contradiction_same_real_output():
    df = _chain(["ls /srv", "echo hi", "ls /srv"], ["a b", "hi", "a b"], ["a b", "hi", "a b c"])
    c = sc.contradiction_candidates(df)
    assert len(c) == 1
    assert (c.iloc[0]["step_a"], c.iloc[0]["step_b"], c.iloc[0]["rule"]) == (0, 2, "same_real_output")


def test_contradiction_read_only_unchanged():
    # Real outputs differ (the file changed in reality), but nothing in the chain wrote to it.
    df = _chain(["cat x.txt", "ls", "cat x.txt"], ["one", "x.txt", "two"], ["one", "x.txt", "three"])
    assert sc.contradiction_candidates(df)["rule"].tolist() == ["read_only_unchanged"]
    # A write to the same file in between explains the change.
    df = _chain(["cat x.txt", "echo 3 > x.txt", "cat x.txt"], ["one", "", "two"], ["one", "", "three"])
    assert sc.contradiction_candidates(df).empty


def test_no_contradiction_when_answers_agree():
    df = _chain(["cat x.txt", "cat x.txt"], ["one", "one"], ["one\n", "one"])
    assert sc.contradiction_candidates(df).empty


def test_flag_requests_and_stub():
    df = _chain(["cat a", "cat b"], ["1", "2"], ["1", "2"])
    reqs = sc.flag_requests(df)
    assert len(reqs) == 1 and [s["step"] for s in reqs[0].steps] == [0, 1]
    assert "output" not in reqs[0].steps[0]  # the flagging model never sees the real outputs


def test_default_matcher_has_the_three_functions():
    m = sc.default_matcher()
    assert callable(m.key_facts) and callable(m.match_facts) and callable(m.verdict)


def test_stub_matcher_round_trip():
    row = {"output": "Error: build failed", "exit_code": 1, "output_status": "complete"}
    facts = sc.STUB_MATCHER.key_facts(row)
    assert facts[0]["value"] == "fail"
    assert sc.STUB_MATCHER.match_facts(facts, "failed", predicted_exit_code=1) == [True]
    assert np.isnan(
        sc.score_answers(
            pd.DataFrame(
                {
                    "case_id": ["z"],
                    "key": ["q"],
                    "situation": ["one_step"],
                    "variant": ["main"],
                    "chain_id": [None],
                    "step": [None],
                    "split": ["test"],
                    "matters": [True],
                }
            ),
            pd.DataFrame({"case_id": ["z"], "parse_ok": [True], "predicted_output": ["x"]}),
            pd.DataFrame(
                {
                    "key": ["q"],
                    "output": [None],
                    "exit_code": [None],
                    "duration_s": [None],
                    "output_status": ["missing"],
                }
            ),
            matcher=sc.STUB_MATCHER,
        )["hit"].iloc[0]
    )


def test_shared_turn_timing_is_left_out_of_the_headline():
    commands = _commands()
    commands["timing_source"] = "next_request"
    commands["turn_calls"] = 1
    commands.loc[commands["key"] == "r/a/1", "turn_calls"] = 3
    s = sc.score_answers(_cases(), _answers(), commands, matcher=MATCHER).set_index("case_id")
    assert s.loc["c1", "shared_turn_timing"] and not s.loc["c1", "timing_scorable"]
    assert s.loc["c1", "timing_finished"]  # still scored, for the sensitivity check
    assert s.loc["c1", "log_error"] == pytest.approx(math.log(2))
    assert s.loc["c2", "timing_scorable"]


def test_timeout_counts_as_finishing_at_the_limit():
    commands = _commands()
    commands.loc[commands["key"] == "r/a/2", ["output", "duration_s"]] = [
        "Command timed out after 300s",
        300.2,
    ]
    s = sc.score_answers(_cases(), _answers(), commands, matcher=MATCHER).set_index("case_id")
    assert s.loc["c2", "timing_scorable"] and s.loc["c2", "real_band"] == "minutes"


def test_answers_for_an_earlier_draw_are_refused():
    answers = _answers()
    answers["key"] = answers["case_id"].map(_cases().set_index("case_id")["key"])
    sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER)  # matching keys: fine
    answers.loc[0, "key"] = "r/a/5"
    with pytest.raises(ValueError, match="redrawn"):
        sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER)


def test_answers_from_another_draw_id_are_refused():
    cases = _cases().assign(draw_id="abc")
    sc.score_answers(cases, _answers().assign(draw_id="abc"), _commands(), matcher=MATCHER)
    with pytest.raises(ValueError, match="draw"):
        sc.score_answers(cases, _answers().assign(draw_id="old"), _commands(), matcher=MATCHER)


def test_unknown_exit_code_is_treated_as_missing():
    answers = _answers()
    answers["predicted_exit_code"] = answers["predicted_exit_code"].astype(object)
    answers.loc[answers["case_id"] == "c3", "predicted_exit_code"] = "unknown"
    s = sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER).set_index("case_id")
    assert pd.isna(s.loc["c3", "pred_verdict"])  # no exit code and no verdict words in the text


def test_not_run_cases_are_left_out_not_missed():
    answers = _answers().assign(status="answered")
    answers.loc[answers["case_id"] == "k1", ["status", "parse_ok", "error"]] = [
        "not_run_after_failure",
        False,
        "x",
    ]
    answers.loc[answers["case_id"] == "c1", ["status", "parse_ok", "error"]] = ["error", False, "timeout"]
    s = sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER).set_index("case_id")
    assert s.loc["k1", "not_run"] and math.isnan(s.loc["k1", "hit"]) and not s.loc["k1", "timing_scorable"]
    assert s.loc["c1", "hit"] == 0.0 and math.isinf(s.loc["c1", "log_error"])  # a failed call is a miss
    assert not s.loc["k2", "after_miss"]  # the step left out is not a miss


def test_content_free_yardstick_is_scored():
    seen = []

    def free(text):
        seen.append(text)
        return "3 tests passed"

    matcher = sc.Matcher(_key_facts, _match, _verdict, free)
    cases = _cases()
    cases["history_keys"] = [["r/a/5"]] + [[] for _ in range(len(cases) - 1)]
    s = sc.score_answers(cases, _answers(), _commands(), matcher=matcher).set_index("case_id")
    assert s.loc["c1", "content_free_hit"] == 1.0  # "3 tests passed" happens to be c1's only fact
    assert s.loc["c2", "content_free_hit"] == 0.0
    assert "answer is 42" in seen[0]  # it was shown the history's outputs
    assert math.isnan(s.loc["c4", "content_free_hit"])  # no facts to check


def test_only_the_answered_splits_are_scored():
    cases = pd.concat([_cases(), _cases().head(1).assign(case_id="p1", split="practice")])
    answers = _answers().assign(split="test")
    s = sc.score_answers(cases, answers, _commands(), matcher=MATCHER)
    assert "p1" not in set(s["case_id"])
    s = sc.score_answers(cases, answers, _commands(), matcher=MATCHER, splits={"test", "practice"})
    assert not s.set_index("case_id").loc["p1", "answered"]


def test_each_instruction_version_is_scored_separately(tmp_path):
    a = _answers().assign(instructions_version="a", model="m")
    b = _answers().assign(instructions_version="b", model="m")
    b.loc[b["case_id"] == "c2", "predicted_output"] = "2 tests FAILED"  # version b gets c2 right
    path = tmp_path / "practice.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in pd.concat([a, b]).to_dict("records")) + "\n")
    answers = sc.read_answers(path)
    assert len(answers) == 2 * len(a)  # one answer per case for each version, not one per case
    s = sc.score_answers(_cases(), answers, _commands(), matcher=MATCHER)
    assert sorted(s["answer_group"].unique()) == ["m / version a", "m / version b"]
    by = s.set_index(["answer_group", "case_id"])["hit"]
    assert by[("m / version a", "c2")] == 0.0 and by[("m / version b", "c2")] == 1.0
    assert (s.groupby("answer_group").size() == len(_cases())).all()


def test_within_two_times_and_duration_bands(scored):
    assert scored.loc["c1", "within2"] == 1.0  # 6 s for 12 s is exactly 2x
    assert scored.loc["c5", "within2"] == 0.0  # no time given
    assert math.isnan(scored.loc["c4", "within2"])  # never finished
    assert scored.loc["c1", "duration_band"] == "5-30 s"
    assert scored.loc["c2", "duration_band"] == "30 s or more"
    assert scored.loc["c3", "duration_band"] == "under 5 s"
