"""Simulated scores where the truth is known, for testing the statistics and checking the plan's
precision table (Appendix B of docs/research/auditor-prediction-plan.md).

A fake auditor is given a true hit rate and a true typical timing error for each situation. Cases are
grouped the way real ones are (several cases per agent, several agents per run; steps within a chain),
and grouped cases are made alike by a shared random effect, sized to give a chosen design effect (how much
the grouping widens the range compared with independent cases).

Run `python -m swarmbench.studies.auditor.simulation` for the precision check; it prints a table and
takes a few minutes.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from swarmbench.studies.auditor import analysis as an

Z_MEDIAN_ABS = 0.6744897501960817  # median of |N(0, 1)|


@dataclass
class Layout:
    """How the cases of one situation are grouped."""

    n_cases: int
    per_cluster: int  # cases per agent (or matter steps per chain)
    clusters_per_run: int  # agents per run (chains: chains per run)
    icc: float  # within-cluster correlation; design effect = 1 + (per_cluster - 1) * icc


# The plan's assumptions: design effect 1.5 for agents, 2.5 for chains.
PLAN_LAYOUTS = {
    "one_step": Layout(120, 3, 4, 0.25),  # 40 agents x 3 cases, 10 runs; deff 1.5
    "chain": Layout(128, 4, 2, 0.5),  # 32 chains x 4 steps that matter; deff 2.5
    "shared": Layout(100, 4, 5, 1 / 6),  # 25 agents x 4 cases, 5 runs; deff 1.5
}


def _beta_probs(rng, p: float, icc: float, n: int) -> np.ndarray:
    """Per-cluster hit probabilities with mean p and intra-cluster correlation icc."""
    if icc <= 0:
        return np.full(n, p)
    s = (1 - icc) / icc
    a, b = max(p * s, 1e-6), max((1 - p) * s, 1e-6)
    return rng.beta(a, b, size=n)


def simulate_situation(
    situation: str,
    *,
    hit_rate: float,
    timing_factor: float,
    layout: Layout,
    rng: np.random.Generator,
    timing_icc: float | None = None,
    run_sd: float = 0.0,
    chain_len: int = 8,
    split: str = "test",
) -> pd.DataFrame:
    """Scores for one situation (main variant, calls that matter).

    Output: each cluster draws a hit probability around hit_rate (beta, correlation layout.icc), and
    each case is a hit with that probability. run_sd adds a run-level shift on the log-odds scale.
    Timing: the signed log ratio is a cluster effect plus noise, normal with total spread chosen so that
    the median absolute log error is ln(timing_factor)."""
    n_clusters = math.ceil(layout.n_cases / layout.per_cluster)
    probs = _beta_probs(rng, hit_rate, layout.icc, n_clusters)
    if run_sd > 0:
        run_of = np.arange(n_clusters) // layout.clusters_per_run
        shift = rng.normal(0, run_sd, size=run_of.max() + 1)[run_of]
        logit = np.log(np.clip(probs, 1e-6, 1 - 1e-6) / np.clip(1 - probs, 1e-6, 1))
        probs = 1 / (1 + np.exp(-(logit + shift)))
    s = math.log(timing_factor) / Z_MEDIAN_ABS
    t_icc = layout.icc if timing_icc is None else timing_icc
    u = rng.normal(0, math.sqrt(t_icc) * s, size=n_clusters)
    rows = []
    for c in range(n_clusters):
        run = f"run{c // layout.clusters_per_run}"
        agent = f"agent-{c}"
        steps = (
            np.sort(rng.choice(chain_len, size=layout.per_cluster, replace=False))
            if situation == "chain"
            else [None] * layout.per_cluster
        )
        for j in range(layout.per_cluster):
            if len(rows) >= layout.n_cases:
                break
            hit = float(rng.random() < probs[c])
            signed = u[c] + rng.normal(0, math.sqrt(1 - t_icc) * s)
            real = float(np.exp(rng.normal(math.log(30), 1.0)))
            pred = real * math.exp(signed)
            rows.append(_row(situation, split, run, agent, c, j, steps[j], hit, real, pred))
    return pd.DataFrame(rows)


def _row(situation, split, run, agent, c, j, step, hit, real, pred, variant="main") -> dict:
    real_band = "seconds" if real < 60 else "minutes"
    pred_band = "seconds" if pred < 60 else "minutes"
    real_fail = (c + j) % 3 == 0
    pred_pass = real_fail and hit == 0.0
    chain_id = f"chain-{c}" if situation == "chain" else None
    return {
        "case_id": f"{situation}-{variant}-{c}-{j}",
        "split": split,
        "situation": situation,
        "variant": variant,
        "key": f"{run}/{agent}/{situation}-{c}-{j}",
        "run_id": run,
        "scenario": f"scenario{int(run[3:]) % 3}",
        "agent": agent,
        "harness": "claude_code",
        "chain_id": chain_id,
        "step": None if step is None else int(step),
        "matters": True,
        "tool_kind": ("quick", "slow", "others", "queue")[(c + j) % 4],
        "answered": True,
        "parse_ok": True,
        "predicted_output": f"output {c} {j} {hit}",
        "hit": hit,
        "facts_right": hit,
        "n_facts": 1,
        "has_verdict": real_fail or (c + j) % 3 == 1,
        "real_verdict": "fail" if real_fail else "pass",
        "pred_verdict": "pass" if pred_pass or not real_fail else "fail",
        "false_pass": float(pred_pass) if real_fail else np.nan,
        "real_seconds": real,
        "timing_scorable": True,
        "log_error": abs(math.log(pred / real)),  # no floor here, so the truth is exact
        "log_ratio": math.log(pred / real),
        "real_band": real_band,
        "pred_band": pred_band,
        "band_right": float(real_band == pred_band),
        "real_waited": real >= 30,
        "wait_right": float(rng_free_wait(c, j)) if situation == "shared" else np.nan,
        "after_miss": False,
    }


def rng_free_wait(c: int, j: int) -> bool:
    return (c * 7 + j) % 5 != 0


def simulate_scores(
    *,
    hit_rate: dict[str, float] | float = 0.9,
    timing_factor: dict[str, float] | float = 1.5,
    layouts: dict[str, Layout] | None = None,
    seed: int = 0,
    with_variants: bool = True,
) -> pd.DataFrame:
    """A full scores table for all three situations, plus (with_variants) the paired variants: 80 chain
    steps re-asked with the real past (hits 15 points higher), 40 shared cases without the record (15
    points lower), and 20 one-step cases with a long history (unchanged)."""
    rng = np.random.default_rng(seed)
    layouts = layouts or PLAN_LAYOUTS
    frames = []
    for situation in an.SITUATIONS:
        hr = hit_rate[situation] if isinstance(hit_rate, dict) else hit_rate
        tf = timing_factor[situation] if isinstance(timing_factor, dict) else timing_factor
        frames.append(
            simulate_situation(situation, hit_rate=hr, timing_factor=tf, layout=layouts[situation], rng=rng)
        )
    df = pd.concat(frames, ignore_index=True)
    if with_variants:
        extra = []
        for situation, variant, n, shift in (
            ("chain", "real_past", 80, 0.15),
            ("shared", "no_record", 40, -0.15),
            ("one_step", "long_history", 20, 0.0),
        ):
            base = df[df["situation"] == situation].head(n)
            for r in base.to_dict("records"):
                p = min(1.0, max(0.0, 0.7 * r["hit"] + 0.27 + shift))
                hit = float(rng.random() < p)
                v = dict(r)
                v.update(
                    case_id=r["case_id"].replace("-main-", f"-{variant}-"),
                    variant=variant,
                    hit=hit,
                    facts_right=hit,
                    log_error=abs(r["log_error"] + rng.normal(0, 0.3)),
                )
                extra.append(v)
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
    # A few calls that don't matter, scored separately.
    nm = df[(df["situation"] == "one_step") & (df["variant"] == "main")].head(30).copy()
    nm["case_id"] = nm["case_id"] + "-nm"
    nm["key"] = nm["key"] + "-nm"
    nm["matters"] = False
    nm["hit"] = (rng.random(len(nm)) < 0.95).astype(float)
    df = pd.concat([df, nm], ignore_index=True)
    return df


# ---- Precision check -----------------------------------------------------------------------------------------


def label_rates(
    situation: str,
    measure: str,
    truth: float,
    *,
    n_sims: int = 300,
    n_boot: int = 2000,
    alpha: float = an.ALPHA / 6,
    layout: Layout | None = None,
    run_sd: float = 0.0,
    seed: int = 1,
    scheme: str | None = None,
) -> dict:
    """How often one headline result is labelled "matches" and "doesn't match" when the truth is known.

    truth is the true hit rate (output) or the true typical factor off (timing). alpha is the level of the
    one-sided test; the default is Holm's strictest step over six results (0.05 / 6), as in the plan.
    Also returns how often the 95% range covered the truth."""
    rng = np.random.default_rng(seed)
    layout = layout or PLAN_LAYOUTS[situation]
    n_match = n_mis = covered = 0
    target = truth if measure == "output" else math.log(truth)
    for _ in range(n_sims):
        df = simulate_situation(
            situation,
            hit_rate=truth if measure == "output" else 0.9,
            timing_factor=truth if measure == "timing" else 1.5,
            layout=layout,
            rng=rng,
            run_sd=run_sd,
        )
        clusters, strata, top = an._cluster_columns(df, situation, scheme)
        vals = df["hit"].to_numpy() if measure == "output" else df["log_error"].to_numpy()
        with an.timing_mode("median"):
            h = an.headline_test(
                vals, clusters, strata, top=top, situation=situation, measure=measure, n_boot=n_boot, rng=rng
            )
        if h.p_match <= alpha and h.p_match <= h.p_mismatch:
            n_match += 1
        elif h.p_mismatch <= alpha and h.p_mismatch < h.p_match:
            n_mis += 1
        covered += h.est.low <= target <= h.est.high
    return {"matches": n_match / n_sims, "doesn't match": n_mis / n_sims, "coverage": covered / n_sims}


# The plan's precision table: (situation, measure, truth, label, claimed chance of that label).
# Output rows: the plan says "labelled matches if truly at least X%, doesn't if at most Y%", read here as
# "with a chance of at least 80%" (the usual meaning of such a threshold).
PLAN_CLAIMS = [
    ("one_step", "output", 0.89, an.MATCHES, 0.80),
    ("one_step", "output", 0.66, an.MISMATCH, 0.80),
    ("chain", "output", 0.91, an.MATCHES, 0.80),
    ("chain", "output", 0.61, an.MISMATCH, 0.80),
    ("shared", "output", 0.90, an.MATCHES, 0.80),
    ("shared", "output", 0.65, an.MISMATCH, 0.80),
    ("one_step", "timing", 1.5, an.MATCHES, 0.98),
    ("one_step", "timing", 4.0, an.MISMATCH, 0.95),
    ("one_step", "timing", 3.0, an.MISMATCH, 0.65),
    ("chain", "timing", 1.5, an.MATCHES, 0.73),
    ("chain", "timing", 4.0, an.MISMATCH, 0.67),
    ("shared", "timing", 1.5, an.MATCHES, 0.95),
    ("shared", "timing", 4.0, an.MISMATCH, 0.92),
    ("shared", "timing", 3.0, an.MISMATCH, 0.56),
]


def check_plan_claims(
    n_sims: int = 300, n_boot: int = 2000, seed: int = 1, scheme: str | None = None
) -> pd.DataFrame:
    rows = []
    for situation, measure, truth, label, claimed in PLAN_CLAIMS:
        r = label_rates(situation, measure, truth, n_sims=n_sims, n_boot=n_boot, seed=seed, scheme=scheme)
        rows.append(
            {
                "situation": situation,
                "measure": measure,
                "truth": truth,
                "label": label,
                "plan_says": claimed,
                "simulated": r[label],
                "coverage_95": r["coverage"],
            }
        )
    return pd.DataFrame(rows)


# The real runs: (scenario, number of runs, agents per run). Run counts are from the plan; agent counts
# are rough.
REAL_STRUCTURE = [
    ("proof_conference", 9, 30),
    ("rival_swarms", 14, 10),
    ("rl_environment", 4, 6),
    ("alder_quotes", 2, 4),
    ("turf_war", 2, 4),
    ("fenwick_routing", 2, 4),
    ("bracken_release", 2, 4),
    ("converter_cutover", 1, 4),
    ("impossible_maths", 1, 4),
]


def simulate_realistic(
    *,
    base_logit: float,
    scenario_effects: np.ndarray,
    run_sd: float,
    agent_sd: float,
    n_cases: int = 120,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Output hits drawn the way the plan draws one-step cases: an equal share of cases per scenario,
    each from a random agent of a random run of that scenario. A hit's log-odds is the base, plus a fixed
    scenario effect, plus a run effect and an agent effect (both random, normal)."""
    rows = []
    per = n_cases // len(REAL_STRUCTURE)
    for (scenario, n_runs, n_agents), a_s in zip(REAL_STRUCTURE, scenario_effects, strict=True):
        r_eff = rng.normal(0, run_sd, size=n_runs)
        g_eff = rng.normal(0, agent_sd, size=(n_runs, n_agents))
        for i in range(per):
            r = int(rng.integers(n_runs))
            g = int(rng.integers(n_agents))
            p = 1 / (1 + np.exp(-(base_logit + a_s + r_eff[r] + g_eff[r, g])))
            rows.append(
                {
                    "scenario": scenario,
                    "run_id": f"{scenario}-{r}",
                    "agent": f"agent-{g}",
                    "chain_id": None,
                    "hit": float(rng.random() < p),
                    "case": i,
                }
            )
    return pd.DataFrame(rows)


def coverage_by_scheme(
    *,
    base_rate: float = 0.85,
    run_sd: float = 0.7,
    agent_sd: float = 0.7,
    scenario_sd: float = 0.7,
    n_sims: int = 300,
    n_boot: int = 2000,
    seed: int = 4,
    schemes: tuple[str, ...] = ("agent_in_run", "agent_in_scenario", "run_in_scenario", "two_stage"),
) -> pd.DataFrame:
    """How often the 95% range covers the true hit rate under each bootstrap grouping, with the real runs'
    structure (REAL_STRUCTURE) and run-to-run and agent-to-agent differences. The truth is the average over
    scenarios of each scenario's expected hit rate over new runs and agents (the plan draws an equal share
    per scenario). Also reports the typical range width."""
    rng = np.random.default_rng(seed)
    base_logit = math.log(base_rate / (1 - base_rate))
    scenario_effects = rng.normal(0, scenario_sd, size=len(REAL_STRUCTURE))
    draws = rng.normal(0, math.sqrt(run_sd**2 + agent_sd**2), size=400_000)
    truth = float(np.mean([np.mean(1 / (1 + np.exp(-(base_logit + a + draws)))) for a in scenario_effects]))
    covered = {s: 0 for s in schemes}
    widths: dict[str, list[float]] = {s: [] for s in schemes}
    for _ in range(n_sims):
        df = simulate_realistic(
            base_logit=base_logit,
            scenario_effects=scenario_effects,
            run_sd=run_sd,
            agent_sd=agent_sd,
            rng=rng,
        )
        for scheme in schemes:
            clusters, strata, top = an._cluster_columns(df, "one_step", scheme)
            est = an.estimate(df["hit"].to_numpy(), clusters, strata, top, n_boot=n_boot, rng=rng)
            covered[scheme] += est.low <= truth <= est.high
            widths[scheme].append(est.high - est.low)
    return pd.DataFrame(
        [
            {
                "scheme": s,
                "coverage_95": covered[s] / n_sims,
                "median_width": float(np.median(widths[s])),
                "truth": truth,
            }
            for s in schemes
        ]
    )


# ---- Precision with the real run structure -----------------------------------------------------------------

# Cases per scenario in each situation. One step: equal shares. Chains: 32 chains, near-equal shares.
# Shared tool: mostly the proof checker, as the plan expects.
REAL_SHARES = {
    "one_step": {name: 14 if i < 3 else 13 for i, (name, _, _) in enumerate(REAL_STRUCTURE)},
    "chain": {name: 4 if i < 5 else 3 for i, (name, _, _) in enumerate(REAL_STRUCTURE)},  # chains
    "shared": {
        "proof_conference": 50,
        "rival_swarms": 20,
        "rl_environment": 15,
        "turf_war": 10,
        "converter_cutover": 5,
    },
    # The final design (user's decision): 200 shared-tool cases, half from waiting-line tools (the
    # proof checker and the RL environment's grader), half from the other shared things, spread
    # equally over the scenarios that have them.
    "shared_split": {
        "proof_conference": 50 + 12,
        "rl_environment": 50 + 12,
        "rival_swarms": 13,
        "alder_quotes": 13,
        "turf_war": 13,
        "fenwick_routing": 13,
        "bracken_release": 12,
        "converter_cutover": 12,
    },
}
CHAIN_MATTER_STEPS = 4
PER_CALL_COST = {"one_step": 0.035, "chain": 0.03 + 8 * 0.020, "shared": 0.051}  # chain: per chain


@dataclass
class Spread:
    """How much results differ between scenarios, runs and agents (or chains). Output effects are on the
    log-odds scale; timing effects are shares of the variance of the signed log error."""

    scenario_sd: float = 0.5
    run_sd: float = 0.5
    unit_sd: float = 1.6  # agent (one step, shared tool)
    chain_sd: float = 3.5  # chain (several steps)
    timing_run_share: float = 0.15
    timing_unit_share: float = 0.25
    timing_chain_share: float = 0.5


def _structure(situation: str) -> list[tuple[str, int, int, int]]:
    """(scenario, runs, agents per run, units drawn) for a situation."""
    shares = REAL_SHARES[situation]
    return [(name, runs, agents, shares[name]) for name, runs, agents in REAL_STRUCTURE if name in shares]


def _calibrate_base(target: float, effects: np.ndarray, weights: np.ndarray, sd: float) -> float:
    """The base log-odds that makes the share-weighted expected hit rate equal target."""
    z = np.random.default_rng(0).normal(0, sd, size=200_000)
    lo, hi = -10.0, 10.0
    for _ in range(60):
        mid = (lo + hi) / 2
        rate = sum(
            w * np.mean(1 / (1 + np.exp(-(mid + a + z)))) for a, w in zip(effects, weights, strict=True)
        )
        lo, hi = (mid, hi) if rate < target else (lo, mid)
    return (lo + hi) / 2


def simulate_real(
    situation: str,
    *,
    hit_rate: float,
    timing_factor: float,
    scale: float = 1.0,
    spread: Spread | None = None,
    scenario_effects: np.ndarray,
    base_logit: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """One simulated set of headline cases for a situation, drawn like the real study: cases (or chains)
    spread over scenarios as REAL_SHARES says, each from a random run and agent of its scenario. `scale`
    multiplies the number of cases. Output: log-odds = base + scenario + run + agent (or chain) effects.
    Timing: signed log error = run + agent (or chain) effects + noise, normal overall, with the median
    absolute value ln(timing_factor)."""
    sp = spread or Spread()
    chain = situation == "chain"
    unit_sd = sp.chain_sd if chain else sp.unit_sd
    s = math.log(timing_factor) / Z_MEDIAN_ABS
    unit_share = sp.timing_chain_share if chain else sp.timing_unit_share
    rows = []
    for (name, n_runs, n_agents, n_units), a_s in zip(_structure(situation), scenario_effects, strict=True):
        r_out = rng.normal(0, sp.run_sd, size=n_runs)
        r_tim = rng.normal(0, math.sqrt(sp.timing_run_share) * s, size=n_runs)
        a_out = rng.normal(0, unit_sd, size=(n_runs, n_agents))
        a_tim = rng.normal(0, math.sqrt(unit_share) * s, size=(n_runs, n_agents))
        for u in range(round(n_units * scale)):
            r = int(rng.integers(n_runs))
            g = int(rng.integers(n_agents))
            if chain:  # every chain is its own unit
                u_out = rng.normal(0, unit_sd)
                u_tim = rng.normal(0, math.sqrt(unit_share) * s)
                n_cases = CHAIN_MATTER_STEPS
            else:
                u_out, u_tim, n_cases = a_out[r, g], a_tim[r, g], 1
            p = 1 / (1 + np.exp(-(base_logit + a_s + r_out[r] + u_out)))
            noise_sd = math.sqrt(max(0.0, 1 - sp.timing_run_share - unit_share)) * s
            for _ in range(n_cases):
                signed = r_tim[r] + u_tim + rng.normal(0, noise_sd)
                rows.append(
                    {
                        "scenario": name,
                        "run_id": f"{name}-{r}",
                        "agent": f"agent-{g}",
                        "chain_id": f"{name}-chain-{u}",
                        "hit": float(rng.random() < p),
                        "log_error": abs(signed),
                    }
                )
    return pd.DataFrame(rows)


def real_label_rates(
    situation: str,
    measure: str,
    truth: float,
    *,
    scale: float = 1.0,
    scheme: str | None = None,
    spread: Spread | None = None,
    n_sims: int = 200,
    n_boot: int = 1000,
    alpha: float = an.ALPHA / 6,
    seed: int = 5,
) -> dict:
    """How often a headline result is labelled each way, with the real run structure (simulate_real).
    Scenario effects are drawn once (seeded) and kept fixed, as scenarios are fixed by the design. Also
    reports how often the 95% range covers the truth and the average measured design effect."""
    sp = spread or Spread()
    rng = np.random.default_rng(seed)
    struct = _structure(situation)
    effects = np.random.default_rng(seed + 1000).normal(0, sp.scenario_sd, size=len(struct))
    # The truth matches the estimand: every scenario equally (the default), or every case equally.
    family = an.WEIGHTING == "family"
    weights = np.ones(len(struct)) if family else np.array([n for *_, n in struct], dtype=float)
    weights /= weights.sum()
    hr = truth if measure == "output" else 0.85
    tf = truth if measure == "timing" else 1.5
    unit_sd = sp.chain_sd if situation == "chain" else sp.unit_sd
    base = _calibrate_base(hr, effects, weights, math.sqrt(sp.run_sd**2 + unit_sd**2))
    target = hr if measure == "output" else math.log(tf)
    n_match = n_mis = covered = 0
    deffs = []
    for _ in range(n_sims):
        df = simulate_real(
            situation,
            hit_rate=hr,
            timing_factor=tf,
            scale=scale,
            spread=sp,
            scenario_effects=effects,
            base_logit=base,
            rng=rng,
        )
        clusters, strata, top = an._cluster_columns(df, situation, scheme)
        vals = df["hit"].to_numpy() if measure == "output" else df["log_error"].to_numpy()
        with an.timing_mode("median"):
            h = an.headline_test(
                vals,
                clusters,
                strata,
                top=top,
                situation=situation,
                measure=measure,
                n_boot=n_boot,
                rng=rng,
                groups=df["scenario"].tolist() if family else None,
            )
        if h.p_match <= alpha and h.p_match <= h.p_mismatch:
            n_match += 1
        elif h.p_mismatch <= alpha and h.p_mismatch < h.p_match:
            n_mis += 1
        covered += h.est.low <= target <= h.est.high
        if not math.isnan(h.est.design_effect):
            deffs.append(h.est.design_effect)
    return {
        "matches": n_match / n_sims,
        "doesn't match": n_mis / n_sims,
        "coverage": covered / n_sims,
        "design_effect": float(np.mean(deffs)) if deffs else float("nan"),
        "n_cases": len(df),
    }


OUTPUT_GRID = (0.55, 0.60, 0.63, 0.66, 0.69, 0.72, 0.88, 0.90, 0.92, 0.94, 0.96, 0.98)
TIMING_GRID = (1.3, 1.45, 1.6, 1.7, 1.8, 2.25, 2.5, 2.75, 3.0, 3.5, 4.0, 5.0)


def _crossing(points: list[tuple[float, float]], level: float = 0.8) -> float | None:
    """The truth at which a label's chance first reaches `level`, by linear interpolation; points are
    (truth, chance) ordered from the line outwards."""
    for (t0, c0), (t1, c1) in itertools.pairwise(points):
        if c0 < level <= c1:
            return t0 + (level - c0) * (t1 - t0) / (c1 - c0)
    if points and points[0][1] >= level:
        return points[0][0]
    return None


def precision_table(
    situation: str,
    *,
    scheme: str | None = None,
    scale: float = 1.0,
    n_sims: int = 200,
    n_boot: int = 1000,
) -> dict:
    """For one situation: the hit rates and timing errors that still get the right label with a chance of
    80% or more, under a bootstrap grouping and a case-count multiplier."""
    out_rows, tim_rows = [], []
    for t in OUTPUT_GRID:
        out_rows.append(
            (
                t,
                real_label_rates(
                    situation, "output", t, scale=scale, scheme=scheme, n_sims=n_sims, n_boot=n_boot
                ),
            )
        )
    for t in TIMING_GRID:
        tim_rows.append(
            (
                t,
                real_label_rates(
                    situation, "timing", t, scale=scale, scheme=scheme, n_sims=n_sims, n_boot=n_boot
                ),
            )
        )
    match_out = _crossing([(t, r["matches"]) for t, r in out_rows if t > an.OUTPUT_LINE])
    mis_out = _crossing([(t, r["doesn't match"]) for t, r in reversed(out_rows) if t < an.OUTPUT_LINE])
    match_tim = _crossing([(t, r["matches"]) for t, r in reversed(tim_rows) if t < 2])
    mis_tim = _crossing([(t, r["doesn't match"]) for t, r in tim_rows if t > 2])
    return {
        "situation": situation,
        "scheme": scheme or an.CLUSTERING,
        "scale": scale,
        "n_cases": out_rows[0][1]["n_cases"],
        "output_matches_if_at_least": match_out,
        "output_doesnt_if_at_most": mis_out,
        "timing_matches_if_at_most": match_tim,
        "timing_doesnt_if_at_least": mis_tim,
        "coverage_output": float(np.mean([r["coverage"] for _, r in out_rows])),
        "coverage_timing": float(np.mean([r["coverage"] for _, r in tim_rows])),
        "design_effect_output": float(np.nanmean([r["design_effect"] for _, r in out_rows])),
        "design_effect_timing": float(np.nanmean([r["design_effect"] for _, r in tim_rows])),
        "grid_output": {t: (r["matches"], r["doesn't match"]) for t, r in out_rows},
        "grid_timing": {t: (r["matches"], r["doesn't match"]) for t, r in tim_rows},
    }


# ---- Coverage and precision on the actual draw ------------------------------------------------------------

# Effect sizes (standard deviations on the log-odds scale for output; for timing, shares of the variance of
# the signed log error). "review": the independent review's values; "earlier": this module's own earlier
# assumptions (Spread's defaults).
SETTINGS = {
    "review, unit sd 1.0": {"family_sd": 0.5, "run_sd": 0.5, "agent_sd": 1.0, "chain_sd": 1.0},
    "review, unit sd 1.5": {"family_sd": 0.5, "run_sd": 0.5, "agent_sd": 1.5, "chain_sd": 1.5},
    "earlier": {"family_sd": 0.5, "run_sd": 0.5, "agent_sd": 1.6, "chain_sd": 3.5},
}
TIMING_SHARES = {"run": 0.15, "unit": 0.25, "chain_unit": 0.5}


def actual_structure(cases: pd.DataFrame, situation: str) -> pd.DataFrame:
    """The headline cases of a situation exactly as drawn (test split, main form, calls that matter), with
    each case's weighting group from the pooling rule."""
    pooled, _ = an.pool_thin_families(cases)
    rows = pooled[
        (pooled["split"] == "test")
        & (pooled["variant"] == "main")
        & (pooled["situation"] == situation)
        & pooled["matters"].fillna(False).astype(bool)
    ]
    return rows[["family", "wfamily", "run_id", "agent", "chain_id"]].reset_index(drop=True)


def _codes(values: pd.Series) -> tuple[np.ndarray, int]:
    codes, uniques = pd.factorize(values.astype(str))
    return codes, len(uniques)


def actual_label_rates(
    structure: pd.DataFrame,
    situation: str,
    measure: str,
    truth: float,
    *,
    setting: str = "review, unit sd 1.5",
    n_sims: int = 200,
    n_boot: int = 1000,
    alpha: float = an.ALPHA / 6,
    seed: int = 6,
) -> dict:
    """Labels, coverage and range width for one headline result on the drawn structure, with a known
    truth. Output: each family has a fixed effect (drawn once), each run and each agent (or chain) a random
    one; the base is set so the estimand (the average over weighting groups, each group's cases equal)
    equals ``truth``. Timing: the signed log error is run + agent (or chain) effects + noise, normal, with
    median absolute value ln(truth)."""
    eff = SETTINGS[setting]
    rng = np.random.default_rng(seed)
    chain = situation == "chain"
    fam_codes, n_fam = _codes(structure["family"])
    run_codes, n_run = _codes(structure["run_id"])
    unit = (
        structure["chain_id"]
        if chain
        else structure["run_id"].astype(str) + "/" + structure["agent"].astype(str)
    )
    unit_codes, n_unit = _codes(unit)
    unit_sd = eff["chain_sd"] if chain else eff["agent_sd"]
    fam_eff = np.random.default_rng(seed + 1000).normal(0, eff["family_sd"], size=n_fam)
    # The estimand: groups equal, cases equal within a group; a family's expected rate is over new runs/units.
    groups = structure["wfamily"].astype(str)
    z = np.random.default_rng(0).normal(0, math.sqrt(eff["run_sd"] ** 2 + unit_sd**2), size=100_000)

    def estimand(base: float) -> float:
        fam_rate = np.array([np.mean(1 / (1 + np.exp(-(base + a + z)))) for a in fam_eff])
        case_rate = pd.Series(fam_rate[fam_codes], index=structure.index)
        return float(case_rate.groupby(groups).mean().mean())

    target = truth if measure == "output" else math.log(truth)
    base = 1.7
    if measure == "output":
        lo, hi = -10.0, 10.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if estimand(mid) < truth else (lo, mid)
        base = (lo + hi) / 2
    s_t = math.log(truth if measure == "timing" else 1.5) / Z_MEDIAN_ABS
    share_unit = TIMING_SHARES["chain_unit" if chain else "unit"]
    clusters, strata, top = an._cluster_columns(structure, situation)
    n_match = n_mis = covered = 0
    widths = []
    for _ in range(n_sims):
        r = rng.normal(0, eff["run_sd"], size=n_run)[run_codes]
        u = rng.normal(0, unit_sd, size=n_unit)[unit_codes]
        if measure == "output":
            p = 1 / (1 + np.exp(-(base + fam_eff[fam_codes] + r + u)))
            vals = (rng.random(len(structure)) < p).astype(float)
        else:
            rt = rng.normal(0, math.sqrt(TIMING_SHARES["run"]) * s_t, size=n_run)[run_codes]
            ut = rng.normal(0, math.sqrt(share_unit) * s_t, size=n_unit)[unit_codes]
            noise = rng.normal(0, math.sqrt(1 - TIMING_SHARES["run"] - share_unit) * s_t, size=len(structure))
            vals = np.abs(rt + ut + noise)
        with an.timing_mode("median"):
            h = an.headline_test(
                vals,
                clusters,
                strata,
                top=top,
                situation=situation,
                measure=measure,
                n_boot=n_boot,
                rng=rng,
                groups=groups.tolist(),
            )
        if h.p_match <= alpha and h.p_match <= h.p_mismatch:
            n_match += 1
        elif h.p_mismatch <= alpha and h.p_mismatch < h.p_match:
            n_mis += 1
        covered += h.est.low <= target <= h.est.high
        widths.append(h.est.high - h.est.low)
    return {
        "matches": n_match / n_sims,
        "doesn't match": n_mis / n_sims,
        "coverage": covered / n_sims,
        "median_width": float(np.median(widths)),
        "n_cases": len(structure),
        "n_groups": int(groups.nunique()),
    }


ACTUAL_OUTPUT_GRID = (0.60, 0.63, 0.66, 0.69, 0.88, 0.90, 0.92, 0.94, 0.96)
ACTUAL_TIMING_GRID = (1.45, 1.6, 1.7, 1.8, 2.5, 2.75, 3.0, 3.5)


def actual_check(
    cases: pd.DataFrame,
    *,
    settings: list[str] | None = None,
    n_sims: int = 200,
    n_boot: int = 1000,
    precision: bool = True,
) -> dict:
    """Coverage (at truths 85% hits and 2x off) and, optionally, the precision thresholds, per situation and
    effect-size setting, on the drawn structure."""
    out: dict = {}
    for situation in an.SITUATIONS:
        st = actual_structure(cases, situation)
        if st.empty:
            continue
        for setting in settings or list(SETTINGS):
            key = f"{situation} | {setting}"
            cov_o = actual_label_rates(
                st, situation, "output", 0.85, setting=setting, n_sims=n_sims, n_boot=n_boot
            )
            cov_t = actual_label_rates(
                st, situation, "timing", 2.0, setting=setting, n_sims=n_sims, n_boot=n_boot
            )
            row = {
                "n_cases": cov_o["n_cases"],
                "n_groups": cov_o["n_groups"],
                "coverage_output": cov_o["coverage"],
                "width_output": cov_o["median_width"],
                "coverage_timing": cov_t["coverage"],
                "width_timing_log": cov_t["median_width"],
            }
            if precision:
                o = [
                    (
                        t,
                        actual_label_rates(
                            st, situation, "output", t, setting=setting, n_sims=n_sims, n_boot=n_boot
                        ),
                    )
                    for t in ACTUAL_OUTPUT_GRID
                ]
                t_ = [
                    (
                        t,
                        actual_label_rates(
                            st, situation, "timing", t, setting=setting, n_sims=n_sims, n_boot=n_boot
                        ),
                    )
                    for t in ACTUAL_TIMING_GRID
                ]
                row["output_matches_if_at_least"] = _crossing(
                    [(t, r["matches"]) for t, r in o if t > an.OUTPUT_LINE]
                )
                row["output_doesnt_if_at_most"] = _crossing(
                    [(t, r["doesn't match"]) for t, r in reversed(o) if t < an.OUTPUT_LINE]
                )
                row["timing_matches_if_at_most"] = _crossing(
                    [(t, r["matches"]) for t, r in reversed(t_) if t < 2]
                )
                row["timing_doesnt_if_at_least"] = _crossing(
                    [(t, r["doesn't match"]) for t, r in t_ if t > 2]
                )
            out[key] = row
            print(key, row, flush=True)
    return out


def drift_power(
    start: float,
    end: float,
    *,
    n_chains: int = 32,
    chain_len: int = 8,
    matter_steps: int = 4,
    chain_sd: float = 1.0,
    n_sims: int = 300,
    alpha: float = 0.05,
    seed: int = 2,
) -> dict:
    """How often the drift test (first half against second half, sign-flip test across chains) and the
    conditional logistic check detect a rise in the error rate from `start` at the first step to `end` at
    the last. Each chain has its own difficulty (normal on the log-odds scale, sd chain_sd); each chain
    has `matter_steps` steps that matter at random positions (only those are scored)."""
    rng = np.random.default_rng(seed)
    t = np.arange(chain_len)
    base = start + (end - start) * t / (chain_len - 1)
    base_logit = np.log(base / (1 - base))
    hits_halves = hits_logit = 0
    for _ in range(n_sims):
        chains, steps, misses = [], [], []
        for c in range(n_chains):
            b = rng.normal(0, chain_sd)
            pos = np.sort(rng.choice(chain_len, size=matter_steps, replace=False))
            p = 1 / (1 + np.exp(-(base_logit[pos] + b)))
            m = (rng.random(matter_steps) < p).astype(float)
            chains += [f"c{c}"] * matter_steps
            steps += list(pos)
            misses += list(m)
        lengths = {f"c{c}": chain_len for c in range(n_chains)}
        dh = an.drift_halves(chains, steps, misses, lengths, rng=rng, n_boot=200)
        hits_halves += dh["p"] is not None and dh["p"] <= alpha
        cl = an.conditional_logit_step(chains, steps, misses)
        hits_logit += cl["p"] is not None and cl["p"] <= alpha
    return {"halves": hits_halves / n_sims, "logistic": hits_logit / n_sims}


def paired_power(
    rate_a: float,
    rate_b: float,
    n_pairs: int,
    *,
    correlation: float = 0.3,
    n_sims: int = 2000,
    alpha: float = 0.05,
    seed: int = 3,
) -> float:
    """How often McNemar's test detects a difference between two paired hit rates. The two answers for
    one command are correlated (a hard command tends to be missed both ways), via a shared normal draw."""
    rng = np.random.default_rng(seed)
    za = _probit(rate_a)
    zb = _probit(rate_b)
    found = 0
    for _ in range(n_sims):
        shared = rng.normal(size=n_pairs)
        ea = math.sqrt(correlation) * shared + math.sqrt(1 - correlation) * rng.normal(size=n_pairs)
        eb = math.sqrt(correlation) * shared + math.sqrt(1 - correlation) * rng.normal(size=n_pairs)
        a = ea < za
        b = eb < zb
        found += an.mcnemar(a, b)["p"] <= alpha
    return found / n_sims


def _probit(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if an.normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Simulation checks of the study's statistics.")
    ap.add_argument("what", choices=["coverage", "plan", "precision", "drift", "paired", "actual"])
    ap.add_argument("--no-precision", action="store_true", help="actual: coverage only")
    ap.add_argument("--situation", default="one_step")
    ap.add_argument("--scheme", default=None)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--sims", type=int, default=200)
    args = ap.parse_args(argv)
    pd.set_option("display.width", 160)
    if args.what == "coverage":
        print("Coverage of the 95% range by bootstrap grouping (real run structure, one step, output):")
        print(coverage_by_scheme(n_sims=args.sims).to_string(index=False))
        print("  ...with no run-to-run differences:")
        print(coverage_by_scheme(run_sd=0.0, n_sims=args.sims).to_string(index=False))
    elif args.what == "plan":
        print("Headline labels with the plan's own assumptions (Holm's strictest step, 0.05/6):")
        print(check_plan_claims(n_sims=args.sims, scheme=args.scheme).to_string(index=False))
    elif args.what == "precision":
        r = precision_table(args.situation, scheme=args.scheme, scale=args.scale, n_sims=args.sims)
        print(json.dumps(r, indent=1, default=str))
    elif args.what == "actual":
        from swarmbench.studies.auditor.score import STUDY_DIR

        cases = pd.read_parquet(
            STUDY_DIR / "cases.parquet",
            columns=[
                "split",
                "variant",
                "situation",
                "family",
                "scenario",
                "run_id",
                "agent",
                "chain_id",
                "matters",
            ],
        )
        r = actual_check(cases, n_sims=args.sims, precision=not args.no_precision)
        print(json.dumps(r, indent=1, default=str))
    elif args.what == "drift":
        print("Drift detection, 32 chains of 8 steps (sign-flip test on halves; logistic check), alpha 0.05:")
        for steps in (4, 8):
            for chain_sd in (0.0, 1.0):
                for end in (0.5, 0.33):
                    r = drift_power(0.2, end, matter_steps=steps, chain_sd=chain_sd, n_sims=args.sims)
                    print(f"  {steps} scored steps, chain sd {chain_sd}, error 0.20 -> {end}: {r}")
    else:
        print("Paired comparisons (McNemar, alpha 0.05, correlation 0.3):")
        for n, a, b in ((80, 0.8, 0.5), (80, 0.8, 0.6), (40, 0.8, 0.5), (40, 0.7, 0.4)):
            print(f"  {n} pairs, {a:.0%} vs {b:.0%}: {paired_power(a, b, n):.2f}")


if __name__ == "__main__":
    main()
