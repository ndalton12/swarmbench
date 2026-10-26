"""Tests for the timing yardsticks (no model calls; synthetic tables)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from swarmbench.studies.auditor import yardsticks as y


def test_family_merges_variants():
    assert y.family("proof-conference-planted-pool15") == "proof-conference"
    assert y.family("proof-conference-native-tools") == "proof-conference"
    assert y.family("rl-coding-env-v2") == "rl-coding-env"
    assert y.family("converter-cutover-low-pressure") == "converter-cutover"
    assert y.family("turf-war") == "turf-war"


def test_command_keys():
    a = "cat << 'EOF' > /w/a.lean\ntheorem x : True := trivial\nEOF\nlean-check /w/a.lean"
    b = "cat << 'EOF' > /w/b.lean\ntheorem y : 1 = 1 := rfl\nEOF\nlean-check /w/b.lean"
    assert y.exact_text("bash", a) != y.exact_text("bash", b)
    assert y.shape("bash", a) == y.shape("bash", b)
    assert y.program("bash", a).endswith("lean-check")
    assert y.program("bash", "cd /w && python3 run.py --n 5 | tail -3").endswith("python3")
    assert y.program("bash", "ls -la /w").endswith("ls")
    assert y.program("Read", '{"file_path": "/w/x"}') == "Read\x00"
    assert y.exact_text("bash", "ls   -la\n/w") == y.exact_text("bash", "ls -la /w")


def test_output_hash_ignores_trailing_space():
    assert y.output_hash("a  \nb\n\n") == y.output_hash("a\nb")
    assert y.output_hash("a") != y.output_hash("b")
    assert y.output_hash(None) is None


def _table(rows):
    df = pd.DataFrame(rows)
    df["t_call"] = df["t"].map(lambda t: datetime.fromtimestamp(t, UTC))
    df["t0"] = df["t"]
    for col, default in (("harness", "claude_code"), ("output_status", "complete"), ("tool_kind", "quick"),
                         ("matters", False), ("function", "bash")):
        if col not in df:
            df[col] = default
    df["family"] = df["scenario"].map(y.family)
    df["k_exact"] = [y.exact_text(f, c) for f, c in zip(df["function"], df["command"])]
    df["k_shape"] = [y.shape(f, c) for f, c in zip(df["function"], df["command"])]
    df["k_prog"] = [y.program(f, c) for f, c in zip(df["function"], df["command"])]
    df["out_hash"] = df["output"].map(y.output_hash)
    df["measured"] = df["duration_s"].notna() & (df["tool_kind"] != "excluded")
    return df


def test_add_load_counts_other_agents_only():
    rows = [
        {"key": "a1", "run_id": "r", "scenario": "s", "agent": "a", "command": "x", "output": "", "t": 0, "duration_s": 100},
        {"key": "a2", "run_id": "r", "scenario": "s", "agent": "a", "command": "x", "output": "", "t": 10, "duration_s": 1},
        {"key": "b1", "run_id": "r", "scenario": "s", "agent": "b", "command": "x", "output": "", "t": 5, "duration_s": 100},
        {"key": "c1", "run_id": "r", "scenario": "s", "agent": "c", "command": "x", "output": "", "t": 20, "duration_s": 1},
    ]
    df = y.add_load(_table(rows)).set_index("key")
    assert df.loc["a2", "load"] == 1  # b1 runs; a1 is the same agent
    assert df.loc["c1", "load"] == 2  # a1 and b1
    assert df.loc["a1", "load"] == 0


def test_repeats_and_spread():
    rows = [
        {"key": "k1", "run_id": "r1", "scenario": "s", "agent": "a", "command": "make test", "output": "ok", "t": 0, "duration_s": 10.0},
        {"key": "k2", "run_id": "r2", "scenario": "s", "agent": "a", "command": "make test", "output": "ok", "t": 0, "duration_s": 20.0},
        {"key": "k3", "run_id": "r2", "scenario": "s", "agent": "b", "command": "make test", "output": "FAIL", "t": 5, "duration_s": 90.0},
        {"key": "k4", "run_id": "r1", "scenario": "s", "agent": "a", "command": "ls", "output": "x", "t": 3, "duration_s": 0.1},
        {"key": "k5", "run_id": "r1", "scenario": "s", "agent": "b", "command": "ls", "output": "x", "t": 4, "duration_s": 0.5},
    ]
    pairs = y.repeat_groups(_table(rows))
    assert len(pairs) == 2  # (k1, k2) and (k4, k5); k3 has a different output
    offs = dict(zip(zip(pairs.key_a, pairs.key_b), pairs.off))
    assert offs[("k1", "k2")] == pytest.approx(2.0)
    assert offs[("k4", "k5")] == pytest.approx(1.0)  # both under the 1-second floor
    spread = y.real_spread(pairs)
    assert spread["k1"] == pytest.approx(2.0) and "k3" not in spread
    s = y.summarise_repeats(pairs)
    assert s["all"]["groups"] == 2 and s["across_runs"]["groups"] == 1


def _rule_rows():
    rows = []
    rng = np.random.default_rng(0)
    for r in range(4):
        for i in range(10):
            # a test suite that takes ~30 s, and a listing that takes ~0.2 s
            rows.append({"key": f"r{r}/t{i}", "run_id": f"r{r}", "scenario": "s", "agent": f"a{i % 3}",
                         "command": "pytest -q tests/", "output": "", "t": i * 100.0,
                         "duration_s": 30.0 * float(rng.uniform(0.8, 1.25)), "tool_kind": "slow"})
            rows.append({"key": f"r{r}/l{i}", "run_id": f"r{r}", "scenario": "s", "agent": f"a{i % 3}",
                         "command": f"ls /w/dir{i}", "output": "", "t": i * 100.0 + 50,
                         "duration_s": 0.2, "tool_kind": "quick"})
    rows.append({"key": "r0/new", "run_id": "r0", "scenario": "s", "agent": "a0", "command": "pytest -q tests/unit",
                 "output": "", "t": 5000.0, "duration_s": 25.0, "tool_kind": "slow"})
    return rows


def test_rule_of_thumb_leave_one_run_out():
    df = y.add_load(_table(_rule_rows()))
    pred = y.rule_of_thumb(df).set_index("key")
    assert len(pred) == len(df)
    # the same command in other runs: about 30 s
    assert pred.loc["r1/t3", "rule_level"] == "exact"
    assert y.times_off(pred.loc["r1/t3", "rule_seconds"], 30.0) < 1.3
    # a listing whose path differs in every run still matches by shape
    assert pred.loc["r2/l4", "rule_level"] in ("exact", "shape")
    assert pred.loc["r2/l4", "rule_seconds"] <= 1.0  # learned in floored (1 s) log time
    # a new command: matched by its shape or program, not by text
    assert pred.loc["r0/new", "rule_level"] in ("shape", "program")
    s = y.summarise_rule(df, pred.reset_index())
    assert s["all"]["typical_off"] < 1.3
    assert set(s["by_kind"]) == {"slow", "quick"}


def test_rule_never_uses_its_own_run():
    rows = _rule_rows()
    # a command that exists only in one run has no exact match anywhere else
    rows.append({"key": "r3/solo", "run_id": "r3", "scenario": "s", "agent": "a0", "command": "./solo.sh",
                 "output": "", "t": 7000.0, "duration_s": 500.0, "tool_kind": "slow"})
    rows.append({"key": "r3/solo2", "run_id": "r3", "scenario": "s", "agent": "a1", "command": "./solo.sh",
                 "output": "", "t": 7100.0, "duration_s": 500.0, "tool_kind": "slow"})
    df = y.add_load(_table(rows))
    pred = y.rule_of_thumb(df).set_index("key")
    assert pred.loc["r3/solo", "rule_level"] != "exact"
    assert pred.loc["r3/solo", "rule_seconds"] < 100  # learned from other runs' slow commands


def test_load_adjustment_learns_slowdown():
    rows = []
    for r in range(3):
        for i in range(30):
            busy = i % 2 == 1
            # under load (4 other agents' commands running) the same command is 4 times slower
            rows.append({"key": f"r{r}/c{i}", "run_id": f"r{r}", "scenario": "s", "agent": "a",
                         "command": "lean-check f.lean", "output": "", "t": i * 1000.0,
                         "duration_s": 40.0 if busy else 10.0, "tool_kind": "queue"})
            if busy:
                for j in range(4):
                    rows.append({"key": f"r{r}/o{i}_{j}", "run_id": f"r{r}", "scenario": "s", "agent": f"b{j}",
                                 "command": "sleep 500", "output": "", "t": i * 1000.0 - 1,
                                 "duration_s": 500.0, "tool_kind": "excluded"})
    df = y.add_load(_table(rows))
    pred = y.rule_of_thumb(df).set_index("key")
    s = y.summarise_rule(df, pred.reset_index())
    assert s["by_kind"]["queue"]["typical_off"] < s["by_kind"]["queue"]["typical_off_unadjusted"]
    assert s["by_kind"]["queue"]["typical_off"] < 1.2
