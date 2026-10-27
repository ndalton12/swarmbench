"""SWE-bench transcripts in the auditor study: made-up mini-swe-agent transcripts only (no downloads, no models)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from swarmbench.studies.auditor import cases as C
from swarmbench.studies.auditor import labels as L
from swarmbench.studies.auditor import prompts as P
from swarmbench.studies.auditor import runner as R
from swarmbench.studies.auditor import score as S
from swarmbench.studies.auditor import swebench as W
from swarmbench.studies.auditor import yardsticks as Y
from swarmbench.studies.auditor.extract import COLUMNS, to_frame

ENTRY = "20260217_mini-v2.0.0_claude-4-6-opus"
TASK = "psf__requests-1234"
DOCKER = ("An error occurred while executing the command: Command '['docker', 'exec', '-w', '/testbed', 'abc123', "
          "'bash', '-c', 'pip install -e .']' timed out after 60 seconds")
GEMINI_ID = "call_9__thought__" + "Eq8B" * 80


def _user(pr: str = "requests.get hangs. It should time out after 60 seconds.", extra: str = "") -> dict:
    return {"role": "user", "content": f"<pr_description>\nConsider the following PR description:\n{pr}\n"
                                       f"</pr_description>\n\n<instructions>\nFix it in /testbed.{extra}\n</instructions>"}


def chat_traj(model: str = "anthropic/claude-opus-4-6", t0: float = 1000.0, user: dict | None = None) -> dict[str, Any]:
    """A transcript in the chat layout: a single command, a reply with two commands, a format error, a
    command stopped by the time limit, then the submit command (whose result ends the run)."""
    msgs = [
        {"role": "system", "content": "You are a helpful assistant that can interact with a computer shell."},
        user or _user(),
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}],
         "extra": {"actions": [{"command": "cat requests/api.py", "tool_call_id": "c1"}], "timestamp": str(t0)}},
        {"role": "tool", "tool_call_id": "c1", "content": "<returncode>0</returncode>...",
         "extra": {"raw_output": "def get(url):\n    pass\n", "returncode": "0", "timestamp": str(t0 + 0.1),
                   "exception_info": ""}},
        {"role": "assistant", "content": "",
         "extra": {"actions": [{"command": "python -m pytest -q tests/test_api.py", "tool_call_id": "c2"},
                               {"command": "git status --short", "tool_call_id": "c3"}], "timestamp": t0 + 10}},
        {"role": "tool", "tool_call_id": "c2",
         "extra": {"raw_output": "F..\n1 failed, 2 passed in 0.50s\n", "returncode": 1, "timestamp": t0 + 13.0}},
        {"role": "tool", "tool_call_id": "c3",
         "extra": {"raw_output": " M requests/api.py\n", "returncode": 0, "timestamp": t0 + 13.0}},
        {"role": "user", "content": "Tool call error", "extra": {"interrupt_type": "FormatError"}},
        {"role": "assistant", "content": "",
         "extra": {"actions": [{"command": "pip install -e .", "tool_call_id": GEMINI_ID}], "timestamp": t0 + 20}},
        {"role": "tool", "tool_call_id": GEMINI_ID,
         "extra": {"raw_output": "Obtaining file:///testbed\n", "returncode": -1, "timestamp": t0 + 80.05,
                   "exception_info": DOCKER, "exception_type": "TimeoutExpired"}},
        {"role": "assistant", "content": "",
         "extra": {"actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt",
                                "tool_call_id": "c5"}], "timestamp": t0 + 90}},
        {"role": "exit", "content": "diff --git a/x b/x", "extra": {"exit_status": "Submitted"}},
    ]
    return {"info": {"mini_version": "2.1.0", "exit_status": "Submitted",
                     "config": {"model": {"model_name": model},
                                "environment": {"image": "docker.io/swebench/sweb.eval.x86_64.psf_1776_requests-1234",
                                                "cwd": "/testbed", "timeout": 60, "interpreter": ["bash", "-c"]}}},
            "messages": msgs, "trajectory_format": "mini-swe-agent-1.1"}


def responses_traj() -> dict[str, Any]:
    """OpenAI models' layout: replies are Responses API objects, results are function_call_output items."""
    t = chat_traj("openai/gpt-5-mini")
    t["messages"] = t["messages"][:2] + [
        {"object": "response", "output": [{"type": "function_call", "call_id": "call_a"}],
         "extra": {"actions": [{"command": "ls", "tool_call_id": "call_a"}], "timestamp": 2000.0}},
        {"type": "function_call_output", "call_id": "call_a", "output": "<returncode>0</returncode>",
         "extra": {"raw_output": "a.py\nb.py\n", "returncode": 0, "timestamp": 2000.25}},
        {"role": "exit", "content": ""},
    ]
    return t


def test_a_transcript_becomes_commands_table_rows():
    rows, info = W.trajectory_rows(chat_traj(), ENTRY, TASK, "raw/x.traj.json")
    df = to_frame(rows)
    assert list(df.columns) == COLUMNS
    assert set(rows[0]) == {*COLUMNS, "family"}
    assert [r["command"].split()[0] for r in rows] == ["cat", "python", "git", "pip", "echo"]
    assert [r["seq"] for r in rows] == [0, 1, 2, 3, 4]
    r0, r1, r2, r3, r4 = rows
    assert r0["run_id"] == f"{ENTRY}__{TASK}" and r0["scenario"] == "swebench" and r0["family"] == "requests"
    assert r0["harness"] == "mini-swe-agent" and r0["agent"] == "agent-1" and r0["agent_model"] == "anthropic/claude-opus-4-6"
    assert json.loads(r0["arguments"]) == {"command": "cat requests/api.py"}
    # one command in its reply: its own time; two: only the reply's total, marked as such
    assert r0["duration_s"] == pytest.approx(0.1, abs=1e-6) and r0["timing_source"] == "trajectory_stamps"
    assert r0["exit_code"] == 0 and r0["output"] == "def get(url):\n    pass\n" and r0["output_status"] == "complete"
    assert r1["duration_s"] == r2["duration_s"] == pytest.approx(3.0) and r1["turn_calls"] == 2
    assert r1["timing_source"] == r2["timing_source"] == "turn_total" and r1["t_call"] == r2["t_call"]
    assert r1["exit_code"] == 1
    # a command stopped at the limit: the harness's notice without the container plumbing, then what it printed
    assert r3["output"] == "Command timed out after 60 seconds\nObtaining file:///testbed\n"
    assert r3["exit_code"] == -1 and r3["duration_s"] == pytest.approx(60.05)
    assert "docker" not in r3["output"]
    # the submit command's result ended the run instead of reaching the agent
    assert r4["output_status"] == "missing" and r4["output"] is None and r4["duration_s"] is None
    # Gemini's thought signature is cut out of the key, which stays unique
    assert r3["key"] == f"{ENTRY}__{TASK}/agent-1/call_9" and len({r["key"] for r in rows}) == 5
    assert (info.commands, info.missing, info.turn_total, info.timeouts, info.format_errors) == (5, 1, 2, 1, 1)


def test_the_responses_layout_is_read_too():
    rows, _ = W.trajectory_rows(responses_traj(), "20260217_mini-v2.0.0_gpt-5-mini", TASK)
    assert len(rows) == 1
    assert rows[0]["output"] == "a.py\nb.py\n" and rows[0]["duration_s"] == pytest.approx(0.25)
    assert rows[0]["agent_model"] == "openai/gpt-5-mini" and rows[0]["result_event"] == "messages[3]"


def test_labels_read_the_rows_like_any_harness():
    rows, _ = W.trajectory_rows(chat_traj(), ENTRY, TASK)
    lab = L.label_table(to_frame(rows)[L.COLUMNS]).set_index("key")
    keys = [r["key"] for r in rows]
    timeout = lab.loc[keys[3]]
    assert timeout["matters"] and "wait" in json.loads(timeout["matters_reasons"])
    facts = json.loads(timeout["facts"])
    assert {"kind": "verdict", "value": "fail"}.items() <= facts[0].items()
    assert any(f.get("value") == "timeout" for f in facts)
    tests = json.loads(lab.loc[keys[1], "facts"])
    assert [f["value"] for f in tests[:2]] == ["fail", "failed=1"]
    assert json.loads(lab.loc[keys[0], "facts"])[0]["kind"] == "outcome"
    assert json.loads(lab.loc[keys[0], "matters_reasons"]) == []


def test_the_description_comes_from_the_transcript_only():
    d = W.describe(chat_traj())
    assert "docker.io/swebench/sweb.eval.x86_64.psf_1776_requests-1234" in d
    assert "starting in /testbed" in d and "`bash -c <command>`" in d and "1 agent, working alone" in d
    assert "You are a helpful assistant" in d and "requests.get hangs" in d and "Fix it in /testbed." in d
    # the issue text mentions 60 seconds, but the agent's instructions don't give the limit
    assert "stopped" not in d
    told = W.describe(chat_traj(user=_user(extra=" Each command times out after 60 seconds.")))
    assert "a command still running after 60 seconds is stopped" in told
    assert W.states_timeout("<pr_description>timeout after 60 seconds</pr_description>", 60) is False


def _listings() -> dict[str, list[str]]:
    big = [f"org__alpha-{i}" for i in range(30)] + [f"org__beta-{i}" for i in range(30)]
    return {f"e{k}": [*big, "org__tiny-1"] for k in range(4)}


def test_the_sample_is_fixed_by_the_seed_and_spread_over_projects():
    plan = W.plan_sample(_listings(), seed=3, main_per_entry=6, extra_per_entry=5)
    assert plan == W.plan_sample(_listings(), seed=3, main_per_entry=6, extra_per_entry=5)
    assert plan != W.plan_sample(_listings(), seed=4, main_per_entry=6, extra_per_entry=5)
    uses = Counter(t for p in plan.values() for t in p["main"])
    assert max(uses.values()) <= W.MAX_USES and uses["org__tiny-1"] == 2  # a tiny project gives what it has
    per_repo = Counter(W.repo_of(t) for t in uses.elements())
    assert per_repo == {"alpha": 11, "beta": 11, "tiny": 2}
    for p in plan.values():
        assert len(p["main"]) == 6 and len(p["extra"]) == 5 and not set(p["main"]) & set(p["extra"])
        assert 2 <= sum(W.repo_of(t) == "alpha" for t in p["main"]) <= 4  # each project spread over the entries


def test_tiny_projects_share_a_family():
    assert W.families(_listings()) == {"alpha": "alpha", "beta": "beta", "tiny": W.SMALL_FAMILY}
    assert W.repo_of("scikit-learn__scikit-learn-10297") == "scikit-learn"
    assert W.repo_of("sphinx-doc__sphinx-8721") == "sphinx"


def test_downloads_are_only_parsed_and_land_where_expected(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        W.raw_path(tmp_path, ENTRY, "../../etc__passwd-1")
    with pytest.raises(ValueError):
        W.raw_path(tmp_path, "not-an-entry", TASK)
    monkeypatch.setattr(W, "_get", lambda url, timeout=60: json.dumps(chat_traj()).encode())
    assert W.download_one(tmp_path, ENTRY, TASK) == (ENTRY, TASK, None)
    assert W.read_transcript(W.raw_path(tmp_path, ENTRY, TASK))["messages"]
    monkeypatch.setattr(W, "_get", lambda url, timeout=60: b"<html>rate limited</html>")
    assert "not JSON" in W.download_one(tmp_path, ENTRY, "psf__requests-9", retries=1)[2]
    assert not W.raw_path(tmp_path, ENTRY, "psf__requests-9").exists()
    assert W.source_url("20260901_mini-v2.4.2_gemini-3-5-flash", TASK).startswith("https://raw.githubusercontent.com/")


def test_short_ids():
    assert W.short_id("toolu_01ABC") == "toolu_01ABC"
    assert W.short_id(GEMINI_ID) == "call_9"
    long = "x" * 100
    assert len(W.short_id(long)) < 64 and W.short_id(long) != W.short_id("x" * 99 + "y")


# --- the whole pipeline on made-up runs -----------------------------------------------------------------------

MODELS = ["anthropic/a", "openai/b", "google/c"]
REPOS = ["alpha", "beta", "gamma"]


def many_runs() -> tuple[pd.DataFrame, dict[str, str]]:
    """Nine single-agent runs (three projects x three models), each a long series of replies."""
    rows, descriptions = [], {}
    for i, (repo, model) in enumerate((r, m) for r in REPOS for m in MODELS):
        t = chat_traj(model, t0=10_000.0 * (i + 1))
        body = t["messages"][2:7]  # a single command, then a reply with two commands
        msgs = t["messages"][:2]
        for k in range(8):
            for m in json.loads(json.dumps(body)):
                ex = m["extra"]
                ex["timestamp"] = float(ex["timestamp"]) + 30 * k
                if m["role"] == "assistant":
                    for a in ex["actions"]:
                        a["tool_call_id"] = f"{a['tool_call_id']}-{k}"
                else:
                    m["tool_call_id"] = f"{m['tool_call_id']}-{k}"
                msgs.append(m)
        t["messages"] = msgs
        task = f"org__{repo}-{i}"
        r, _ = W.trajectory_rows(t, ENTRY, task)
        rows.extend(r)
        descriptions[f"{ENTRY}__{task}"] = W.describe(t)
    df = to_frame(rows)
    df["family"] = [r["family"] for r in rows]
    return df, descriptions


SIZES = C.DrawSizes(one_step_matter=6, one_step_other=3, long_history=0, repeats=0, chains=3, chain_real_past=3,
                    shared=0, shared_no_record=0, queue_moments=0, practice_one_step=2, practice_one_step_other=1,
                    practice_chains=1, practice_shared=0, practice_runs=1, spread_runs=True, max_per_run=1,
                    balance_column="agent_model")


async def test_draw_dry_run_and_score_work_for_single_agent_runs(tmp_path):
    df, descriptions = many_runs()
    labels = L.label_table(df[L.COLUMNS])
    commands = C.normalise_commands(df)
    assert set(commands["family"]) == set(REPOS)  # the table's own family, not one from the scenario
    draw = C.draw_cases(commands, labels, seed=7, sizes=SIZES)
    c = draw.cases
    again = C.draw_cases(commands, labels, seed=7, sizes=SIZES).cases
    pd.testing.assert_frame_equal(c.reset_index(drop=True), again.reset_index(drop=True))
    # practice: whole runs, kept apart from the test cases
    prac, test = set(c.loc[c.split == "practice", "run_id"]), set(c.loc[c.split == "test", "run_id"])
    assert len(prac) == 1 and not prac & test
    assert set(c["situation"]) == {"one_step", "chain"} and len(draw.queue) == 0
    one = c[(c.split == "test") & (c.situation == "one_step")]
    assert one[one.matters].groupby("run_id").size().max() == 1  # at most max_per_run from one run
    assert set(one["family"]) == set(REPOS)
    models = one.merge(commands[["key", "agent_model"]], on="key")["agent_model"].value_counts()
    assert models.max() - models.min() <= 1
    assert len(c[(c.split == "test") & (c.situation == "chain")]["chain_id"].unique()) == 3
    # the runner uses the saved descriptions; the dry run answers every test ask; scoring reads them back
    data = tmp_path / "data"
    C.save(draw, data)
    (data / P.RUN_DESCRIPTIONS_FILE).write_text(json.dumps(descriptions))
    df.to_parquet(data / "commands.parquet")
    labels.to_parquet(data / "labels.parquet")
    cases, queue = C.load_cases(data)
    s = R.Settings(batch="t", dry_run=True, data_dir=data, runs_dir=tmp_path / "no-runs", quiet=True,
                   mock_style="oracle")
    run = R.AuditorRun(s, cases, queue, C.load_commands(data / "commands.parquet"))
    rid = cases["run_id"].iloc[0]
    assert run.description(rid) == descriptions[rid]
    summary = await run.run()
    assert summary["statuses"] == {"answered": int((cases.split == "test").sum())}
    reqs = [json.loads(x) for x in (data / "answers" / "t_requests.jsonl").read_text().splitlines()]
    assert all("Docker container started from the image" in r["messages"][0]["text"] for r in reqs)
    inputs = S.load_inputs(data, "t")
    scores = S.score_answers(inputs["cases"], inputs["answers"], inputs["commands"], inputs["labels"])
    scored = scores[scores["hit"].notna()]
    assert len(scored) and scored["hit"].mean() == 1.0  # the oracle mock repeats the truth
    # commands timed only as part of a several-command reply stay out of the timing headline
    turn = scores[scores["timing_source"] == "turn_total"]
    assert len(turn) and not turn["timing_scorable"].any() and turn["shared_turn_timing"].all()


def test_the_rule_of_thumb_learns_from_extra_runs_and_keeps_the_family(tmp_path):
    df, _ = many_runs()
    labels = L.label_table(df[L.COLUMNS])
    own = df[df["run_id"].str.endswith(("-0", "-1"))]
    extra = df[~df["run_id"].isin(own["run_id"])]
    own.to_parquet(tmp_path / "commands.parquet")
    labels.to_parquet(tmp_path / "labels.parquet")
    extra.to_parquet(tmp_path / "commands_extra.parquet")
    labels.to_parquet(tmp_path / "labels_extra.parquet")
    t = Y.load_table(data_dir=tmp_path)
    assert set(t["family"]) == {"alpha"}  # from the table's family column, not the scenario
    assert Y.main(["--data", str(tmp_path), "--extra-commands", "commands_extra.parquet",
                   "--extra-labels", "labels_extra.parquet"]) == 0
    yt = pd.read_parquet(tmp_path / "yardstick_timing.parquet")
    assert set(yt["key"]) == set(own["key"])  # predictions for the case pool only
    measured = yt[yt["key"].isin(own.loc[own["duration_s"].notna(), "key"])]
    assert measured["rule_seconds"].notna().all()
    # one agent per run: nothing else runs at the same time, so the load adjustment changes nothing
    assert (yt["load"].fillna(0) == 0).all()
    assert (measured["rule_seconds"] == measured["rule_seconds_plain"]).all()


def test_spread_over_runs_takes_runs_in_turn_and_balances():
    runs = ["a"] * 5 + ["b"] * 5 + ["c"] * 5
    rng = C.rng_for(1, "x")
    got = C.spread_over_runs(pd.Series(runs).to_numpy(), 6, rng, max_per_run=2)
    assert Counter(runs[i] for i in got) == {"a": 2, "b": 2, "c": 2}
    used: Counter[str] = Counter({"m1": 5})
    got = C.spread_over_runs(pd.Series(runs).to_numpy(), 2, C.rng_for(1, "y"), None, {"a": "m1", "b": "m2", "c": "m3"}, used)
    assert {runs[i] for i in got} == {"b", "c"}  # the model already used least goes first
    assert used == {"m1": 5, "m2": 1, "m3": 1}


def test_turn_totals_count_as_shared_turn_timing():
    assert S.shared_turn_timing({"timing_source": "turn_total", "turn_calls": 2})
    assert not S.shared_turn_timing({"timing_source": "trajectory_stamps", "turn_calls": 1})
    assert S.shared_turn_timing({"timing_source": "next_request", "turn_calls": 3})


def test_saved_descriptions_are_optional(tmp_path):
    assert P.saved_description(tmp_path, "r") is None
    (tmp_path / P.RUN_DESCRIPTIONS_FILE).write_text(json.dumps({"r": "about r"}))
    assert P.saved_description(tmp_path, "r") == "about r"
    assert P.saved_description(tmp_path, "other") is None


def test_build_tables_writes_the_study_files(tmp_path):
    plan = {ENTRY: {"main": [TASK], "extra": ["mwaskom__seaborn-3069"]}}
    for task in (TASK, "mwaskom__seaborn-3069"):
        p = W.raw_path(tmp_path / "raw", ENTRY, task)
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(chat_traj()))
    t = W.build_tables(tmp_path, plan, {ENTRY: [TASK, "mwaskom__seaborn-3069", *[f"psf__requests-{i}" for i in range(9)]]})
    main = pd.read_parquet(tmp_path / "commands.parquet")
    assert list(main.columns) == [*COLUMNS, "family"] and set(main["family"]) == {"requests"}
    extra = pd.read_parquet(tmp_path / "commands_extra.parquet")
    assert set(extra["family"]) == {W.SMALL_FAMILY}  # seaborn: one task in this listing
    assert set(json.loads((tmp_path / W.DESCRIPTIONS_FILE).read_text())) == {f"{ENTRY}__{TASK}"}
    inv = pd.read_parquet(tmp_path / "runs_inventory.parquet")
    assert set(inv["part"]) == {"main", "extra"} and "resolved" not in " ".join(inv.columns)
    assert t["missing"] == []


@pytest.fixture(autouse=True)
def _no_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Nothing here touches the real study folders."""
    monkeypatch.setattr(W, "study_dir", lambda: tmp_path / "study")
