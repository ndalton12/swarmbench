"""Tests for the auditor study's statistics, mostly on simulated data where the truth is known."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from swarmbench.studies.auditor import analysis as an
from swarmbench.studies.auditor import simulation as sim

# ---- Building blocks -----------------------------------------------------------------------------------------


def test_binom_cdf_matches_direct_sum():
    assert an.binom_cdf(1, 10, 0.5) == pytest.approx(11 / 1024)
    assert an.binom_cdf(10, 10, 0.3) == 1.0
    assert an.binom_cdf(-1, 10, 0.3) == 0.0


def test_holm_known_example():
    reject, adj = an.holm([0.01, 0.04, 0.03, 0.005], alpha=0.05)
    # Sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06 -> stop.
    assert reject == [True, False, False, True]
    assert adj[3] == pytest.approx(0.02)
    assert adj[0] == pytest.approx(0.03)
    assert adj[2] == pytest.approx(0.06)
    assert adj[1] == pytest.approx(0.06)  # monotone


def test_holm_ignores_missing():
    reject, adj = an.holm([0.01, float("nan")], alpha=0.05)
    assert reject == [True, False]
    assert adj[0] == pytest.approx(0.01)
    assert math.isnan(adj[1])


def test_benjamini_hochberg_known_example():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    reject, adj = an.benjamini_hochberg(p, q=0.05)
    assert reject == [True, True] + [False] * 8
    assert adj[0] == pytest.approx(0.01)
    assert adj[1] == pytest.approx(0.04)


def test_mcnemar_exact():
    a = [True] * 9 + [False] * 1 + [True] * 5
    b = [False] * 9 + [True] * 1 + [True] * 5
    r = an.mcnemar(a, b)
    assert (r["only_first"], r["only_second"]) == (9, 1)
    assert r["p"] == pytest.approx(2 * 11 / 1024)
    assert an.mcnemar([True, False], [True, False])["p"] == 1.0


def test_wilcoxon_exact_small_cases():
    # All six differences positive: one arrangement out of 2^6 is as extreme on each side.
    assert an.wilcoxon_signed_rank([1, 2, 3, 4, 5, 6])["p"] == pytest.approx(2 / 64)
    # Symmetric differences: no evidence.
    assert an.wilcoxon_signed_rank([1, -1, 2, -2, 3, -3])["p"] == pytest.approx(1.0)
    # Pairs and zeros: zeros are dropped.
    r = an.wilcoxon_signed_rank([5, 6, 7, 1], [1, 2, 3, 1])
    assert r["n_used"] == 3
    assert r["p"] == pytest.approx(2 / 8)


def test_wilcoxon_handles_infinite_errors():
    x = [math.inf, 3.0, 2.0, 4.0, 5.0, math.inf]
    y = [math.inf, 1.0, 1.0, 1.0, 1.0, 1.0]
    r = an.wilcoxon_signed_rank(x, y)
    assert r["n_used"] == 5  # inf - inf is dropped, inf - 1 is the largest difference
    assert r["p"] == pytest.approx(2 / 32)


def test_wilcoxon_normal_approximation_large_sample():
    rng = np.random.default_rng(0)
    assert an.wilcoxon_signed_rank(rng.normal(1.0, 1.0, 200))["p"] < 1e-6
    assert an.wilcoxon_signed_rank(rng.normal(0.0, 1.0, 200))["p"] > 0.001


def test_weighted_median_is_the_ordinary_median_with_unit_weights():
    for x in ([3.0, 1.0, 2.0], [4.0, 1.0, 3.0, 2.0], [1.0, math.inf, 2.0]):
        assert an.weighted_median(np.array(x), np.ones((1, len(x))))[0] == pytest.approx(np.median(x))


def test_bootstrap_weights_keep_strata_and_clusters():
    rng = np.random.default_rng(1)
    clusters = ["a", "a", "b", "c", "c", "c"]
    strata = ["r1", "r1", "r1", "r2", "r2", "r2"]
    w = an.bootstrap_weights(clusters, strata, n_boot=500, rng=rng)
    assert w.shape == (500, 6)
    # Cases of one cluster always share a weight.
    assert np.all(w[:, 0] == w[:, 1])
    assert np.all((w[:, 3] == w[:, 4]) & (w[:, 4] == w[:, 5]))
    # Stratum r1 has two clusters: they are redrawn twice in all; r2 has one, always drawn once.
    assert np.all(w[:, 0] + w[:, 2] == 2)
    assert np.all(w[:, 3] == 1)


def test_bootstrap_weights_two_stage():
    rng = np.random.default_rng(2)
    clusters = ["r1/a", "r1/b", "r2/c", "r3/d", "r3/e"]
    top = ["r1", "r1", "r2", "r3", "r3"]
    strata = ["s", "s", "s", "t", "t"]
    w = an.bootstrap_weights(clusters, strata, top, n_boot=2000, rng=rng)
    # Stratum t has one run with two agents: always 2 agent-draws in all.
    assert np.all(w[:, 3] + w[:, 4] == 2)
    # Stratum s has two runs: one fewer (one run) is redrawn each time, bringing its own agents.
    total = w[:, 0] + w[:, 1] + w[:, 2]
    assert set(np.unique(total)) == {1.0, 2.0}  # r2 alone (1 agent) or r1 alone (2 agent-draws)
    assert np.all((w[:, 2] == 0) | (w[:, 0] + w[:, 1] == 0))


def test_textbook_run_count_is_selectable(monkeypatch):
    monkeypatch.setattr(an, "RUNS_DRAWN", "k")
    rng = np.random.default_rng(2)
    clusters = ["r1/a", "r1/b", "r2/c"]
    w = an.bootstrap_weights(clusters, ["s"] * 3, ["r1", "r1", "r2"], n_boot=2000, rng=rng)
    assert set(np.unique(w.sum(axis=1))) <= {2.0, 3.0, 4.0}


def test_bootstrap_rejects_cluster_in_two_strata():
    with pytest.raises(ValueError):
        an.bootstrap_weights(["a", "a"], ["r1", "r2"], n_boot=10, rng=np.random.default_rng(0))


def test_median_order_statistic_range():
    lo, hi = an.median_ci_order(np.arange(1, 101))
    assert (lo, hi) == (40, 61)  # the textbook ranks for n = 100
    assert all(math.isnan(v) for v in an.median_ci_order([1.0, 2.0, 3.0]))


def test_sign_flip_test():
    rng = np.random.default_rng(0)
    assert an.sign_flip_test([1.0] * 10, rng=rng) == pytest.approx(2 / 1024)
    assert an.sign_flip_test([1.0, -1.0] * 5, rng=rng) == 1.0
    assert an.sign_flip_test(np.full(30, 0.5), rng=rng) < 0.001


def test_conditional_logit_recovers_slope():
    rng = np.random.default_rng(3)
    groups, x, y = [], [], []
    for c in range(600):
        b = rng.normal(0, 1.0)
        for t in range(8):
            p = 1 / (1 + math.exp(-(-1.5 + b + 0.3 * t)))
            groups.append(c)
            x.append(t)
            y.append(float(rng.random() < p))
    r = an.conditional_logit_step(groups, x, y)
    assert r["slope"] == pytest.approx(0.3, abs=0.06)
    assert r["p"] < 1e-6
    flat = an.conditional_logit_step(groups, x, list(rng.permutation(y)))
    assert flat["p"] > 0.001


def test_drift_halves_detects_strong_drift():
    rng = np.random.default_rng(4)
    chains, steps, misses = [], [], []
    for c in range(60):
        for t in range(8):
            chains.append(f"c{c}")
            steps.append(t)
            misses.append(float(rng.random() < (0.1 if t < 4 else 0.7)))
    r = an.drift_halves(chains, steps, misses, rng=rng, n_boot=500)
    assert r["estimate"] == pytest.approx(0.6, abs=0.1)
    assert r["p"] < 0.001
    assert r["low"] < r["estimate"] < r["high"]


# ---- Headline labels on simulated auditors with a known truth ------------------------------------------------


@pytest.fixture(scope="module")
def known_truth_results():
    scores = sim.simulate_scores(
        hit_rate={"one_step": 0.95, "chain": 0.55, "shared": 0.80},
        timing_factor={"one_step": 1.3, "chain": 4.0, "shared": 2.0},
        seed=11,
    )
    return scores, an.run_analysis(scores, n_boot=2000, seed=5)


def _label(results, situation, measure):
    return next(h for h in results["headline"] if h["situation"] == situation and h["measure"] == measure)


def test_good_auditor_matches(known_truth_results):
    _, res = known_truth_results
    assert _label(res, "one_step", "output")["label"] == an.MATCHES
    assert _label(res, "one_step", "timing")["label"] == an.MATCHES


def test_poor_auditor_does_not_match(known_truth_results):
    _, res = known_truth_results
    assert _label(res, "chain", "output")["label"] == an.MISMATCH
    assert _label(res, "chain", "timing")["label"] == an.MISMATCH


def test_borderline_auditor_cant_tell(known_truth_results):
    _, res = known_truth_results
    assert _label(res, "shared", "output")["label"] == an.CANT_TELL
    assert _label(res, "shared", "timing")["label"] == an.CANT_TELL


def test_headline_ranges_and_counts(known_truth_results):
    _, res = known_truth_results
    h = _label(res, "one_step", "output")
    assert h["low"] <= h["estimate"] <= h["high"]
    assert h["n"] == 120
    t = _label(res, "chain", "timing")
    assert t["factor"] == pytest.approx(math.exp(t["estimate"]))
    assert t["order_low"] <= t["estimate"] <= t["order_high"]
    assert res["settings"]["clustering"] == an.CLUSTERING
    assert len(res["headline"]) == 6


def test_parts_are_tested_and_corrected(known_truth_results):
    _, res = known_truth_results
    groups = {p["group"] for p in res["parts"]}
    for g in (
        "by scenario",
        "by tool kind",
        "false passes",
        "time band",
        "drift",
        "own past against real past",
        "record of the others",
        "long history",
        "calls that don't matter",
    ):
        assert g in groups, g
    tested = [p for p in res["parts"] if p["p"] is not None]
    assert tested and all(p["p_bh"] is not None and p["p_bh"] >= p["p"] - 1e-12 for p in tested)
    own = next(
        p for p in res["parts"] if p["group"] == "own past against real past" and p["subset"] == "output"
    )
    assert own["estimate"] > 0  # the simulation makes the real past 15 points better


def test_no_data_is_labelled_no_data():
    scores = sim.simulate_scores(seed=1, with_variants=False)
    scores = scores[scores["situation"] != "shared"]
    res = an.run_analysis(scores, n_boot=200)
    assert _label(res, "shared", "output")["label"] == an.NO_DATA


def test_missing_prediction_counts_as_infinite_timing_error():
    rng = np.random.default_rng(0)
    errs = np.array([0.1] * 5 + [math.inf] * 6)
    h = an.headline_test(
        errs, [f"a{i}" for i in range(11)], None, situation="one_step", measure="timing", n_boot=500, rng=rng
    )
    assert math.isinf(h.est.value)


def test_false_alarm_rate_at_the_line():
    """At a truth exactly on the line, a single one-sided test at 5% labels the result (wrongly, either
    way) at most about 10% of the time (5% each way)."""
    rng = np.random.default_rng(9)
    layout = sim.Layout(120, 3, 4, 0.25)
    labelled = 0
    n = 120
    for _ in range(n):
        df = sim.simulate_situation("one_step", hit_rate=0.8, timing_factor=2.0, layout=layout, rng=rng)
        c, s, t = an._cluster_columns(df, "one_step")
        h = an.headline_test(
            df["hit"].to_numpy(), c, s, top=t, situation="one_step", measure="output", n_boot=500, rng=rng
        )
        labelled += min(h.p_match, h.p_mismatch) <= 0.05
    assert labelled / n <= 0.16


@pytest.mark.parametrize("scheme", ["agent_in_run", "agent_in_scenario", "run_in_scenario", "two_stage"])
def test_every_clustering_scheme_runs(scheme):
    df = sim.simulate_situation(
        "one_step",
        hit_rate=0.9,
        timing_factor=1.5,
        layout=sim.PLAN_LAYOUTS["one_step"],
        rng=np.random.default_rng(0),
    )
    c, s, t = an._cluster_columns(df, "one_step", scheme)
    est = an.estimate(df["hit"].to_numpy(), c, s, t, n_boot=300, rng=np.random.default_rng(1))
    assert est.low <= est.value <= est.high


def test_queue_scoring():
    q = pd.DataFrame(
        {
            "real_typical_wait_s": [10.0, 100.0],
            "typical_wait_s": [20.0, 100.0],
            "sim_typical_wait_s": [10.0, 50.0],
            "real_waiting_5min": [1, 4],
            "waiting_5min": [2, 4],
            "real_waiting_10min": [2, 6],
            "waiting_10min": [2, 9],
            "real_hits_limit": [False, True],
            "hits_limit": [False, False],
        }
    )
    s = an.score_queue(q)
    assert s["auditor_wait_error"].tolist() == pytest.approx([math.log(2), 0.0])
    assert s["program_wait_error"].tolist() == pytest.approx([0.0, math.log(2)])
    assert s["auditor_waiting_10min_error"].tolist() == [0, 3]
    assert s["auditor_limit_right"].tolist() == [1.0, 0.0]


# ---- The simulation helpers themselves -----------------------------------------------------------------------


def test_label_rates_quick():
    r = sim.label_rates("one_step", "output", 0.97, n_sims=20, n_boot=300)
    assert r["matches"] >= 0.8
    r = sim.real_label_rates("shared", "timing", 5.0, n_sims=10, n_boot=300)
    assert r["doesn't match"] >= 0.8


def test_actual_structure_simulation_runs():
    rows = []
    for fam, runs in (("big", 4), ("mid", 2), ("thin", 1)):
        for r in range(runs):
            for a in range(3):
                rows.append(
                    {
                        "split": "test",
                        "variant": "main",
                        "situation": "one_step",
                        "family": fam,
                        "scenario": fam,
                        "run_id": f"{fam}-{r}",
                        "agent": f"a{a}",
                        "chain_id": None,
                        "matters": True,
                    }
                )
    st = sim.actual_structure(pd.DataFrame(rows), "one_step")
    assert len(st) == 21 and st["wfamily"].nunique() == 3  # a lone thin family keeps its own share
    r = sim.actual_label_rates(st, "one_step", "output", 0.97, n_sims=5, n_boot=200)
    assert 0 <= r["coverage"] <= 1 and r["n_groups"] == 3


def test_crossing_interpolates():
    assert sim._crossing([(0.88, 0.5), (0.9, 0.7), (0.92, 0.9)]) == pytest.approx(0.91)
    assert sim._crossing([(0.88, 0.9)]) == 0.88
    assert sim._crossing([(0.88, 0.1), (0.9, 0.2)]) is None


def test_every_family_counts_equally():
    rng = np.random.default_rng(0)
    y = np.array([1.0] * 100 + [0.0] * 10)
    fam = ["a"] * 100 + ["b"] * 10
    clusters = [f"{f}{i}" for i, f in enumerate(fam)]
    est = an.estimate(y, clusters, fam, n_boot=500, rng=rng, groups=fam)
    assert est.value == pytest.approx(0.5)
    assert est.low == pytest.approx(0.5) and est.high == pytest.approx(0.5)  # each family is all one value
    pooled = an.estimate(y, clusters, fam, n_boot=500, rng=rng)
    assert pooled.value == pytest.approx(100 / 110)
    groups = ["a"] * 100 + ["b"] * 10 + ["c"] * 10
    values = np.array([0.1] * 100 + [5.0] * 10 + [3.0] * 10)
    med = an.estimate(
        values, [str(i) for i in range(120)], None, stat="median", n_boot=50, rng=rng, groups=groups
    )
    assert med.value == pytest.approx(3.0)  # families a, b and c each hold a third of the weight


def test_calls_without_content_are_reported_apart():
    scores = sim.simulate_scores(seed=2, with_variants=False)
    scores["content_facts"] = True
    one = scores.index[(scores["situation"] == "one_step") & scores["matters"]][:10]
    scores.loc[one, "content_facts"] = False
    scores["content_free_hit"] = 0.1
    res = an.run_analysis(scores, n_boot=200)
    assert _label(res, "one_step", "output")["n"] == 110
    apart = [p for p in res["parts"] if p["group"] == "facts without content"]
    assert apart and apart[0]["n"] == 10
    free = [p for p in res["parts"] if p["group"] == "content-free yardstick" and p["subset"] == "all"]
    assert free and free[0]["estimate"] == pytest.approx(0.1)


def test_thin_families_are_pooled():
    rows = []
    for fam, runs, chains_per_run in (("big", 4, 2), ("thin1", 1, 2), ("thin2", 1, 1), ("fewchains", 2, 1)):
        for r in range(runs):
            for c in range(chains_per_run):
                rows.append(
                    {
                        "split": "test",
                        "variant": "main",
                        "situation": "chain",
                        "family": fam,
                        "run_id": f"{fam}-r{r}",
                        "agent": "a",
                        "chain_id": f"{fam}-r{r}-c{c}",
                    }
                )
    for fam, runs in (("big", 3), ("solo", 1)):
        for r in range(runs):
            rows.append(
                {
                    "split": "test",
                    "variant": "main",
                    "situation": "one_step",
                    "family": fam,
                    "run_id": f"{fam}-r{r}",
                    "agent": "a",
                    "chain_id": None,
                }
            )
    out, summary = an.pool_thin_families(pd.DataFrame(rows))
    chain = out[out["situation"] == "chain"].groupby("family")["wfamily"].first().to_dict()
    assert chain["big"] == "big"
    assert chain["thin1"] == chain["thin2"] == chain["fewchains"] == "other: fewchains, thin1, thin2"
    one = out[out["situation"] == "one_step"].groupby("family")["wfamily"].first().to_dict()
    assert one == {"big": "big", "solo": "solo"}  # a lone thin family has nothing to pool with
    assert {r["family"]: r["thin"] for r in summary["one_step"]} == {"big": False, "solo": True}


def test_leave_one_family_out(known_truth_results):
    _, res = known_truth_results
    rows = res["leave_one_family_out"]
    assert len(rows) == 6 * 3  # six results x three scenarios in the simulated data
    assert all(r["flipped"] == (r["label"] != r["full_label"]) for r in rows)
    assert {r["dropped"] for r in rows} == {"scenario0", "scenario1", "scenario2"}
    h = _label(res, "one_step", "output")
    assert h["n_families"] == 3 and h["pooled_estimate"] is not None
