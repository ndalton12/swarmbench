from __future__ import annotations

import itertools

import pandas as pd
import pytest

from swarmbench.studies.auditor import cases as C
from tests.studies.auditor.runner_fixtures import NoQueue, make_commands, no_real_queue  # noqa: F401

SMALL = C.DrawSizes(one_step_matter=12, one_step_other=4, long_history=3, repeats=3, chains=4, chain_real_past=6,
                    shared=8, shared_no_record=3, queue_moments=3, practice_one_step=4, practice_one_step_other=1,
                    practice_chains=1, practice_shared=2)


@pytest.fixture(scope="module")
def commands() -> pd.DataFrame:
    return C.normalise_commands(make_commands())


@pytest.fixture(scope="module")
def draw(commands) -> C.Draw:
    return C.draw_cases(commands, C.stub_labels(commands), seed=11, sizes=SMALL, queue_tools=NoQueue)


def test_allocate_gives_equal_shares_and_passes_on_what_small_groups_lack():
    assert C.allocate(9, {"a": 100, "b": 100, "c": 100}) == {"a": 3, "b": 3, "c": 3}
    assert C.allocate(9, {"a": 1, "b": 100, "c": 100}) == {"a": 1, "b": 4, "c": 4}
    assert sum(C.allocate(10, {"a": 2, "b": 3}).values()) == 5  # can't give more than exists
    assert C.allocate(10, {"a": 100, "b": 100}, cap_share=0.3) == {"a": 3, "b": 3}


def test_the_draw_is_repeatable_and_the_seed_matters(commands, draw):
    again = C.draw_cases(commands, C.stub_labels(commands), seed=11, sizes=SMALL, queue_tools=NoQueue)
    pd.testing.assert_frame_equal(draw.cases.reset_index(drop=True), again.cases.reset_index(drop=True))
    other = C.draw_cases(commands, C.stub_labels(commands), seed=12, sizes=SMALL, queue_tools=NoQueue)
    assert set(other.cases["key"]) != set(draw.cases["key"])
    # row order of the input doesn't change the draw
    shuffled = commands.sample(frac=1, random_state=3)
    third = C.draw_cases(C.normalise_commands(shuffled), C.stub_labels(shuffled), seed=11, sizes=SMALL, queue_tools=NoQueue)
    assert list(third.cases["case_id"] + third.cases["key"]) == list(draw.cases["case_id"] + draw.cases["key"])


def test_practice_cases_come_from_other_agents_of_the_same_runs(commands, draw):
    c = draw.cases
    practice_units = set(zip(c.loc[c.split == "practice", "run_id"], c.loc[c.split == "practice", "agent"]))
    test_units = set(zip(c.loc[c.split == "test", "run_id"], c.loc[c.split == "test", "agent"]))
    assert practice_units and test_units and not practice_units & test_units
    # whole agents, never whole runs: every run keeps test agents
    df = C.with_labels(commands, C.stub_labels(commands))
    units = C.practice_units(df, 11)
    assert units
    for run_id, g in df.groupby("run_id"):
        assert set(g["agent"]) - {a for r, a in units if r == run_id}  # at least one test agent left
    # spread over families: at most one agent per family unless more were needed for practice chains
    fams = df.drop_duplicates(["run_id", "agent"]).set_index(["run_id", "agent"])["family"]
    per_family = pd.Series([fams[u] for u in units]).value_counts()
    assert per_family.max() <= 2 and len(per_family) == df["family"].nunique()


def test_a_familys_chains_come_from_several_runs_when_it_can():
    import numpy as np

    starts = pd.DataFrame({"key": [f"k{i}" for i in range(6)], "family": "f",
                           "run_id": ["r1"] * 4 + ["r2"] * 2, "agent": "a", "i": [0, 10, 20, 30, 0, 10]})
    for seed in range(10):
        got = C.pick_chains(starts, 3, np.random.default_rng(seed))
        assert len(got) == 3 and {c["run_id"] for c in got} == {"r1", "r2"}


def test_draw_sizes_and_variants(draw):
    c = draw.cases
    test = c[c.split == "test"]
    one = test[(test.situation == "one_step") & (test.variant == "main")]
    assert one["matters"].sum() == 12 and (~one["matters"]).sum() == 4
    assert (test.variant == "long_history").sum() == 3 and (test.variant == "repeat").sum() == 3
    # shared cases: half from tools where jobs wait their turn, half from other shared things, as far as
    # each side has candidates (a shortfall is noted, never filled from the other side)
    shared = test[(test.situation == "shared") & (test.variant == "main")]
    waiting = shared["shared_thing"].isin(C.WAITING_THINGS)
    assert waiting.sum() <= 4 and (~waiting).sum() <= 4
    for side, n in (("waiting", waiting.sum()), ("other", (~waiting).sum())):
        assert n == 4 or any(f"on {side} things" in note for note in draw.notes)
    nr = test[test.variant == "no_record"]
    assert len(nr) <= 3 and nr["shared_thing"].isin(C.WAITING_THINGS).sum() <= 2
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


def test_a_run_the_queue_program_cannot_read_gets_empty_values_and_a_note(commands):
    class Broken(NoQueue):
        @staticmethod
        def queue_truth(run_id, t):
            raise FileNotFoundError(f"runs/{run_id}/compose.yaml")

    df = C.with_labels(commands, C.stub_labels(commands))
    df["split"] = "test"
    notes: list[str] = []
    q = C.draw_queue_moments(df, 5, 1, Broken, notes)
    assert len(q) == 1 and q["slots"].isna().all() and q["sim_typical_wait_s"].isna().all()
    assert any("FileNotFoundError" in n for n in notes)


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


def test_chain_packing_never_falls_short_when_starts_allow():
    import numpy as np

    starts = pd.DataFrame({"key": ["k1", "k5", "k9"], "family": "f", "run_id": "r", "agent": "a", "i": [1, 5, 9]})
    for seed in range(20):
        got = C.pick_chains(starts, 2, np.random.default_rng(seed))
        assert sorted(c["i"] for c in got) == [1, 9]


def test_unfinished_commands_are_listed_by_one_rule_whatever_happened_later():
    t = pd.Timestamp("2026-01-01T12:00Z")
    rows = pd.DataFrame({
        "key": ["later", "never", "old-never", "me"], "agent": ["b", "c", "d", "a"], "shared_thing": "x",
        "t_call": [t - pd.Timedelta(minutes=20), t - pd.Timedelta(minutes=20), t - pd.Timedelta(minutes=40), t],
        "t_result": [t + pd.Timedelta(minutes=1), pd.NaT, pd.NaT, t + pd.Timedelta(seconds=5)],
        "output_status": ["complete", "missing", "missing", "complete"]})
    me = next(rows[rows.key == "me"].itertuples(index=False))
    finished, running = C.record_of_others(rows, me)
    assert finished == [] and running == ["later", "never"]


def test_draw_id_changes_with_the_draw(draw):
    other = C.Draw(cases=draw.cases.copy(), queue=draw.queue.copy())
    assert C.draw_id(other) == C.draw_id(draw)
    other.cases.loc[other.cases.index[0], "key"] = "something/else/x"
    assert C.draw_id(other) != C.draw_id(draw)
