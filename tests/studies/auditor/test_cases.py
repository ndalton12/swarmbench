from __future__ import annotations

import itertools

import pandas as pd
import pytest

from swarmbench.studies.auditor import cases as C
from tests.studies.auditor.runner_fixtures import make_commands

SMALL = C.DrawSizes(one_step_matter=12, one_step_other=4, long_history=3, repeats=3, chains=4, chain_real_past=6,
                    shared=8, shared_no_record=3, queue_moments=3, practice_one_step=4, practice_one_step_other=1,
                    practice_chains=1, practice_shared=2)


@pytest.fixture(scope="module")
def commands() -> pd.DataFrame:
    return C.normalise_commands(make_commands())


@pytest.fixture(scope="module")
def draw(commands) -> C.Draw:
    return C.draw_cases(commands, C.stub_labels(commands), seed=11, sizes=SMALL)


def test_allocate_gives_equal_shares_and_passes_on_what_small_groups_lack():
    assert C.allocate(9, {"a": 100, "b": 100, "c": 100}) == {"a": 3, "b": 3, "c": 3}
    assert C.allocate(9, {"a": 1, "b": 100, "c": 100}) == {"a": 1, "b": 4, "c": 4}
    assert sum(C.allocate(10, {"a": 2, "b": 3}).values()) == 5  # can't give more than exists
    assert C.allocate(10, {"a": 100, "b": 100}, cap_share=0.3) == {"a": 3, "b": 3}


def test_the_draw_is_repeatable_and_the_seed_matters(commands, draw):
    again = C.draw_cases(commands, C.stub_labels(commands), seed=11, sizes=SMALL)
    pd.testing.assert_frame_equal(draw.cases.reset_index(drop=True), again.cases.reset_index(drop=True))
    other = C.draw_cases(commands, C.stub_labels(commands), seed=12, sizes=SMALL)
    assert set(other.cases["key"]) != set(draw.cases["key"])
    # row order of the input doesn't change the draw
    shuffled = commands.sample(frac=1, random_state=3)
    third = C.draw_cases(C.normalise_commands(shuffled), C.stub_labels(shuffled), seed=11, sizes=SMALL)
    assert list(third.cases["case_id"] + third.cases["key"]) == list(draw.cases["case_id"] + draw.cases["key"])


def test_practice_cases_come_from_other_agents_and_runs(commands, draw):
    c = draw.cases
    practice_units = set(zip(c.loc[c.split == "practice", "run_id"], c.loc[c.split == "practice", "agent"]))
    test_units = set(zip(c.loc[c.split == "test", "run_id"], c.loc[c.split == "test", "agent"]))
    assert practice_units and test_units and not practice_units & test_units
    # turf war has two runs: one whole run is practice
    tw_practice_runs = {r for r, _ in practice_units if r.startswith("run-tw")}
    tw_test_runs = {r for r, _ in test_units if r.startswith("run-tw")}
    assert len(tw_practice_runs) <= 1 and not tw_practice_runs & tw_test_runs


def test_draw_sizes_and_variants(draw):
    c = draw.cases
    test = c[c.split == "test"]
    one = test[(test.situation == "one_step") & (test.variant == "main")]
    assert one["matters"].sum() == 12 and (~one["matters"]).sum() == 4
    assert (test.variant == "long_history").sum() == 3 and (test.variant == "repeat").sum() == 3
    assert (test.variant == "no_record").sum() == 3
    assert (test.variant == "real_past").sum() == 6
    assert test.case_id.is_unique and c.case_id.is_unique
    # the same command is never a main case in two situations
    mains = c[c.variant == "main"]
    assert mains["key"].is_unique


def test_chains_are_consecutive_and_hold_calls_that_matter(commands, draw):
    chains = draw.cases[(draw.cases.situation == "chain") & (draw.cases.variant == "main")]
    seqs = commands.set_index("key")["seq"]
    for _, g in chains.groupby("chain_id"):
        g = g.sort_values("step")
        assert list(g["step"]) == list(range(C.CHAIN_LEN))
        s = [int(seqs[k]) for k in g["key"]]
        assert s == list(range(s[0], s[0] + C.CHAIN_LEN))
        assert g["matters"].sum() >= C.CHAIN_MIN_MATTER
        assert g["agent"].nunique() == 1
        # every step sees the same real past, from before the chain
        assert all(list(h) == list(g["history_keys"].iloc[0]) for h in g["history_keys"])
        assert all(int(seqs[k]) < s[0] for k in g["history_keys"].iloc[0])
    real = draw.cases[draw.cases.variant == "real_past"]
    for r in real.itertuples():
        hist = [int(seqs[k]) for k in r.history_keys]
        assert hist and max(hist) == int(seqs[r.key]) - 1  # the real past up to that step


def test_record_of_others_never_shows_what_came_later(commands, draw):
    df = C.with_labels(commands, C.stub_labels(commands))
    by_key = df.set_index("key")
    shared = draw.cases[(draw.cases.situation == "shared") & (draw.cases.variant == "main")]
    assert len(shared)
    for r in shared.itertuples():
        t = by_key.loc[r.key, "t_call"]
        for k in r.record_keys:
            assert by_key.loc[k, "t_result"] <= t  # finished before the question
            assert by_key.loc[k, "t_call"] >= t - pd.Timedelta(seconds=C.RECORD_WINDOW_S)
        for k in r.running_keys:
            assert by_key.loc[k, "t_call"] < t
            tr = by_key.loc[k, "t_result"]
            assert pd.isna(tr) or tr > t
        others = {by_key.loc[k, "agent"] for k in list(r.record_keys) + list(r.running_keys)} - {r.agent}
        assert others
    norec = draw.cases[draw.cases.variant == "no_record"]
    assert all(len(x) == 0 for x in norec["record_keys"])


def test_history_is_before_the_command(commands, draw):
    seqs = commands.set_index("key")["seq"]
    for r in draw.cases[draw.cases.situation == "one_step"].itertuples():
        hist = [int(seqs[k]) for k in r.history_keys]
        assert all(h < int(seqs[r.key]) for h in hist)
        if r.variant == "main":
            assert len(hist) <= C.HISTORY_LEN


def test_queue_moments_are_spread_out(draw):
    q = draw.queue
    assert len(q) >= 1 and set(q.columns) >= set(C.QUEUE_TRUTH_KEYS + C.QUEUE_SIM_KEYS)
    for _, g in q.groupby("run_id"):
        t = sorted(g["t_freeze"])
        assert all((b - a).total_seconds() >= C.QUEUE_GAP_S for a, b in itertools.pairwise(t))


def test_queue_values_come_from_the_queue_program_when_present(commands):
    class FakeQueue:
        @staticmethod
        def is_checker_call(cmd):
            return "lean-check" in cmd

        @staticmethod
        def queue_truth(run_id, t):
            return {"slots": 3, "real_typical_wait_s": 12.0, "real_waiting_5min": 1, "real_waiting_10min": 0,
                    "real_hits_limit": False}

        @staticmethod
        def queue_forecast(run_id, t):
            return {"sim_typical_wait_s": 10.0, "sim_waiting_5min": 1, "sim_waiting_10min": 0, "sim_hits_limit": False}

    df = C.with_labels(commands, C.stub_labels(commands))
    df["split"] = "test"
    q = C.draw_queue_moments(df, 5, 1, FakeQueue)
    assert len(q) == 1 and set(q["slots"]) == {3} and set(q["sim_typical_wait_s"]) == {10.0}


def test_save_and_load_round_trip(tmp_path, draw):
    C.save(draw, tmp_path, {"seed": 11})
    cases, queue = C.load_cases(tmp_path)
    assert len(cases) == len(draw.cases) and len(queue) == len(draw.queue)
    assert isinstance(cases["history_keys"].iloc[0], list)


def test_labels_file_is_used_when_present(tmp_path, commands):
    labels = C.stub_labels(commands)
    labels["matters"] = True
    p = tmp_path / "labels.parquet"
    labels.to_parquet(p)
    got, source = C.load_labels(commands, p)
    assert got["matters"].all() and str(p) == source
    labels.drop(columns=["tool_kind"]).to_parquet(p)
    with pytest.raises(ValueError):
        C.load_labels(commands, p)
