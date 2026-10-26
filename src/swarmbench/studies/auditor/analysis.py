"""Statistics for the auditor prediction study (stage 7).

Reads the scored answers made by `score.py` and produces the six headline results, the parts, and the
numbers the report shows. Everything here follows Appendix B of docs/research/auditor-prediction-plan.md:

- Ranges come from a cluster bootstrap: whole agents are redrawn together within their run (one step and
  shared tool), and whole chains together (several steps), so related cases are never treated as
  independent.
- Each headline result gets a one-sided test against its line (80% hits for output; a typical error of a
  factor of 2 for timing), in the direction its estimate points. The six are corrected together with
  Holm's method at 5%. A result is labelled "matches", "doesn't match" or "can't tell".
- The parts are tested with Benjamini-Hochberg at 10%.
- Paired comparisons use McNemar's exact test (hits) and the Wilcoxon signed-rank test (timing errors).
- Drift compares error rates in the first and second half of each chain (sign-flip test across chains),
  checked with a conditional logistic regression on step number (each chain its own baseline).

Only numpy and the standard library are used. Every random draw comes from one seeded generator, so the
same inputs and seed give the same numbers.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---- Fixed settings (pre-registered; see docs/research/auditor-prediction-prereg.md) --------------------

OUTPUT_LINE = 0.80  # share of calls that matter with every key fact right
TIMING_LINE = math.log(2.0)  # typical (median) absolute log error: a factor of 2
ALPHA = 0.05  # family-wise error over the six headline results (Holm)
BH_Q = 0.10  # false discovery rate over the parts (Benjamini-Hochberg)
N_BOOT = 10_000
SEED = 20261026
LEVEL = 0.95

SITUATIONS = ("one_step", "chain", "shared")
SITUATION_NAMES = {
    "one_step": "One step, real past",
    "chain": "Several steps, own past",
    "shared": "Shared tool under load",
}
MEASURES = ("output", "timing")

MATCHES = "matches"
MISMATCH = "doesn't match"
CANT_TELL = "can't tell"
NO_DATA = "no data"


# ---- Small distribution helpers ----------------------------------------------------------------------------


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    lc = math.lgamma(n + 1)
    total = 0.0
    for i in range(k + 1):
        total += math.exp(lc - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
    return min(1.0, total)


# ---- Multiple testing ---------------------------------------------------------------------------------------


def holm(pvalues: Sequence[float], alpha: float = ALPHA) -> tuple[list[bool], list[float]]:
    """Holm's step-down method. Returns (reject, adjusted p) in the input order. NaN p-values are never
    rejected and do not count towards the family size."""
    p = np.asarray(pvalues, dtype=float)
    idx = [i for i in range(len(p)) if not np.isnan(p[i])]
    m = len(idx)
    reject = [False] * len(p)
    adjusted = [float("nan")] * len(p)
    order = sorted(idx, key=lambda i: p[i])
    running = 0.0
    still = True
    for rank, i in enumerate(order):
        adj = min(1.0, (m - rank) * p[i])
        running = max(running, adj)
        adjusted[i] = running
        if still and p[i] <= alpha / (m - rank):
            reject[i] = True
        else:
            still = False
    return reject, adjusted


def benjamini_hochberg(pvalues: Sequence[float], q: float = BH_Q) -> tuple[list[bool], list[float]]:
    """Benjamini-Hochberg step-up method. Returns (reject, adjusted p) in the input order; NaN p-values are
    skipped."""
    p = np.asarray(pvalues, dtype=float)
    idx = [i for i in range(len(p)) if not np.isnan(p[i])]
    m = len(idx)
    reject = [False] * len(p)
    adjusted = [float("nan")] * len(p)
    if m == 0:
        return reject, adjusted
    order = sorted(idx, key=lambda i: p[i])
    k_max = 0
    for rank, i in enumerate(order, start=1):
        if p[i] <= q * rank / m:
            k_max = rank
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * m / rank)
        adjusted[i] = min(1.0, running)
    for rank, i in enumerate(order, start=1):
        reject[i] = rank <= k_max
    return reject, adjusted


# ---- Cluster bootstrap --------------------------------------------------------------------------------------


def _membership(children: np.ndarray, parents: Sequence, what: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for c, p in zip(children, parents, strict=True):
        if out.setdefault(int(c), str(p)) != str(p):
            raise ValueError(f"a {what} belongs to more than one group: {p!r}")
    return out


def bootstrap_weights(
    clusters: Sequence,
    strata: Sequence | None = None,
    top: Sequence | None = None,
    *,
    n_boot: int = N_BOOT,
    rng: np.random.Generator,
) -> np.ndarray:
    """Case weights for a stratified cluster bootstrap, shape (n_boot, n_cases).

    Without `top`: in each stratum, its clusters (agents, or chains) are redrawn with replacement, as many
    as it has; every case gets the number of times its cluster was drawn. With no strata, all clusters
    are redrawn together.

    With `top` (two stages): in each stratum, the top-level groups (runs) are redrawn with replacement;
    then within every drawn run, its clusters are redrawn with replacement."""
    clusters = list(clusters)
    n = len(clusters)
    strata = [0] * n if strata is None else list(strata)
    cluster_codes, cluster_index = np.unique(np.array([str(c) for c in clusters]), return_inverse=True)
    counts = np.zeros((n_boot, len(cluster_codes)), dtype=np.float64)
    if top is None:
        stratum_of = _membership(cluster_index, strata, "cluster")
        by_stratum: dict[str, list[int]] = {}
        for c, s in stratum_of.items():
            by_stratum.setdefault(s, []).append(c)
        for members in by_stratum.values():
            k = len(members)
            counts[:, members] = rng.multinomial(k, np.full(k, 1.0 / k), size=n_boot)
        return counts[:, cluster_index]
    _, top_index = np.unique(np.array([str(t) for t in top]), return_inverse=True)
    top_of = _membership(cluster_index, top_index, "cluster")
    stratum_of_top = _membership(top_index, strata, "run")
    members_of_top: dict[int, list[int]] = {}
    for c, t in top_of.items():
        members_of_top.setdefault(int(t), []).append(c)
    tops_in_stratum: dict[str, list[int]] = {}
    for t, s in stratum_of_top.items():
        tops_in_stratum.setdefault(s, []).append(t)
    for tops in tops_in_stratum.values():
        r = len(tops)
        top_counts = rng.multinomial(r, np.full(r, 1.0 / r), size=n_boot)
        for j, t in enumerate(tops):
            members = members_of_top[t]
            k = len(members)
            # Redrawing a run m times, each time redrawing its k clusters, is one draw of m*k.
            counts[:, members] = rng.multinomial(top_counts[:, j] * k, np.full(k, 1.0 / k))
    return counts[:, cluster_index]


def equalize_groups(weights: np.ndarray, group_index: np.ndarray) -> np.ndarray:
    """Rescale case weights (shape (B, n)) so every group's weights sum to 1 in every row. A group with
    no weight in a row stays at 0 (it then simply drops out of that row)."""
    out = np.array(weights, dtype=float, copy=True)
    for g in np.unique(group_index):
        cols = group_index == g
        total = out[:, cols].sum(axis=1, keepdims=True)
        out[:, cols] = np.divide(out[:, cols], total, out=np.zeros_like(out[:, cols]), where=total > 0)
    return out


def weighted_mean(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Row-wise weighted mean; weights has shape (B, n)."""
    total = weights.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (weights @ values) / total


def weighted_median(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Row-wise weighted median; with unit weights this is the ordinary median (middle two averaged).
    Infinite values are allowed (a missing prediction counts as an infinite error)."""
    values = np.asarray(values, dtype=float)
    weights = np.atleast_2d(weights)
    order = np.argsort(values, kind="stable")
    v = values[order]
    w = weights[:, order]
    cum = np.cumsum(w, axis=1)
    half = cum[:, -1:] / 2.0
    lo = np.argmax(cum >= half - 1e-9, axis=1)
    hi = np.argmax(cum > half + 1e-9, axis=1)
    a, b = v[lo], v[hi]
    with np.errstate(invalid="ignore"):
        out = np.where(a == b, a, (a + b) / 2.0)
    return out


def _statistic(stat: str):
    if stat == "mean":
        return weighted_mean
    if stat == "median":
        return weighted_median
    raise ValueError(stat)


@dataclass
class Estimate:
    """A point estimate with a cluster-bootstrap range."""

    value: float
    low: float
    high: float
    n: int
    n_clusters: int
    boot: np.ndarray = field(repr=False, default_factory=lambda: np.array([]))
    design_effect: float = float("nan")

    def as_dict(self) -> dict:
        return {
            "estimate": _clean(self.value),
            "low": _clean(self.low),
            "high": _clean(self.high),
            "n": self.n,
            "n_clusters": self.n_clusters,
            "design_effect": _clean(self.design_effect),
        }


def _clean(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    if math.isnan(x):
        return None
    return x


def estimate(
    values: Sequence[float],
    clusters: Sequence,
    strata: Sequence | None = None,
    top: Sequence | None = None,
    *,
    stat: str = "mean",
    n_boot: int = N_BOOT,
    rng: np.random.Generator,
    level: float = LEVEL,
    groups: Sequence | None = None,
) -> Estimate:
    """Point estimate and percentile cluster-bootstrap range. Also measures the design effect: how much
    the grouping widens the range compared with treating every case as independent (variance ratio).

    With ``groups`` (scenario families), every group gets equal weight, in the estimate and in every
    redraw: the mean is the average of the groups' means, the median is the median with each case
    weighted by one over its group's (redrawn) size."""
    y = np.asarray(values, dtype=float)
    n = len(y)
    if n == 0:
        return Estimate(float("nan"), float("nan"), float("nan"), 0, 0)
    f = _statistic(stat)
    gidx = None
    if groups is not None:
        _, gidx = np.unique(np.array([str(g) for g in groups]), return_inverse=True)

    def eq(weights: np.ndarray) -> np.ndarray:
        return weights if gidx is None else equalize_groups(weights, gidx)

    value = float(f(y, eq(np.ones((1, n))))[0])
    w = bootstrap_weights(clusters, strata, top, n_boot=n_boot, rng=rng)
    boot = f(y, eq(w))
    a = (1 - level) / 2
    finite = boot[~np.isnan(boot)]
    with np.errstate(invalid="ignore"):  # infinite errors are allowed; quantiles handle them
        low, high = np.quantile(finite, [a, 1 - a]) if len(finite) else (np.nan, np.nan)
    # Independent-case bootstrap for the design effect.
    w_iid = rng.multinomial(n, np.full(n, 1.0 / n), size=min(n_boot, 4000)).astype(float)
    boot_iid = f(y, eq(w_iid))
    deff = float("nan")
    fb, fi = boot[np.isfinite(boot)], boot_iid[np.isfinite(boot_iid)]
    if len(fb) > 1 and len(fi) > 1 and np.var(fi) > 0:
        deff = float(np.var(fb) / np.var(fi))
    n_clusters = len({str(c) for c in clusters})
    return Estimate(value, float(low), float(high), n, n_clusters, boot, deff)


def one_sided_p(boot: np.ndarray, line: float, side: str) -> float:
    """Bootstrap one-sided p-value against a line, by inverting the percentile range.

    side="above": evidence that the truth is above the line (null: at or below it).
    side="below": evidence that the truth is below the line (null: at or above it)."""
    b = boot[~np.isnan(boot)]
    if len(b) == 0:
        return float("nan")
    bad = np.sum(b <= line) if side == "above" else np.sum(b >= line)
    return float((1 + bad) / (1 + len(b)))


# ---- Order-statistic range for a median (no distribution assumed, no grouping) -------------------------------


def median_ci_order(values: Sequence[float], level: float = LEVEL) -> tuple[float, float]:
    """Distribution-free range for a median from ordered values. Treats cases as independent, so it is a
    cross-check on the bootstrap range, not a replacement."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    a = (1 - level) / 2
    j = 0  # 1-based index of the lower order statistic
    for cand in range(1, n // 2 + 1):
        if binom_cdf(cand - 1, n, 0.5) <= a:
            j = cand
        else:
            break
    if j == 0:
        return float("nan"), float("nan")
    return float(x[j - 1]), float(x[n - j])


# ---- Headline tests -----------------------------------------------------------------------------------------


@dataclass
class Headline:
    situation: str
    measure: str
    est: Estimate
    p_match: float
    p_mismatch: float
    order_ci: tuple[float, float] | None = None
    p_holm: float = float("nan")
    label: str = NO_DATA
    pooled: Estimate | None = None
    """The same result with every case weighted equally (scenarios with more cases count more)."""
    n_families: int = 0

    @property
    def line(self) -> float:
        return OUTPUT_LINE if self.measure == "output" else TIMING_LINE

    @property
    def p_directional(self) -> float:
        """The p-value of the one-sided test in the direction the estimate points."""
        if self.est.n == 0:
            return float("nan")
        return min(self.p_match, self.p_mismatch)

    @property
    def direction(self) -> str:
        return MATCHES if self.p_match <= self.p_mismatch else MISMATCH

    def as_dict(self) -> dict:
        d = {
            "situation": self.situation,
            "situation_name": SITUATION_NAMES.get(self.situation, self.situation),
            "measure": self.measure,
            "line": self.line,
            **self.est.as_dict(),
            "p_match": _clean(self.p_match),
            "p_mismatch": _clean(self.p_mismatch),
            "p_holm": _clean(self.p_holm),
            "label": self.label,
            "n_families": self.n_families,
        }
        if self.pooled is not None and self.pooled.n:
            d["pooled_estimate"] = _clean(self.pooled.value)
            d["pooled_low"] = _clean(self.pooled.low)
            d["pooled_high"] = _clean(self.pooled.high)
        if self.measure == "timing":
            d["factor"] = _clean(math.exp(self.est.value)) if np.isfinite(self.est.value) else None
            d["factor_low"] = _factor(self.est.low)
            d["factor_high"] = _factor(self.est.high)
            if self.order_ci is not None:
                d["order_low"], d["order_high"] = _clean(self.order_ci[0]), _clean(self.order_ci[1])
        return d


def _factor(x: float) -> float | None:
    if x is None or math.isnan(x):
        return None
    return float(math.exp(x)) if np.isfinite(x) else float("inf")


def headline_test(
    values: Sequence[float],
    clusters: Sequence,
    strata: Sequence | None,
    *,
    top: Sequence | None = None,
    situation: str,
    measure: str,
    n_boot: int = N_BOOT,
    rng: np.random.Generator,
    groups: Sequence | None = None,
) -> Headline:
    """One headline result: estimate, range and both one-sided p-values against the line.

    Output: values are hits (1/0), the statistic is the mean, "matches" means above 80%.
    Timing: values are absolute log errors, the statistic is the median, "matches" means below log 2."""
    if measure == "output":
        est = estimate(values, clusters, strata, top, stat="mean", n_boot=n_boot, rng=rng, groups=groups)
        if est.n == 0:
            return Headline(situation, measure, est, float("nan"), float("nan"))
        p_match = one_sided_p(est.boot, OUTPUT_LINE, "above")
        p_mismatch = one_sided_p(est.boot, OUTPUT_LINE, "below")
        return Headline(situation, measure, est, p_match, p_mismatch)
    est = estimate(values, clusters, strata, top, stat="median", n_boot=n_boot, rng=rng, groups=groups)
    if est.n == 0:
        return Headline(situation, measure, est, float("nan"), float("nan"))
    p_match = one_sided_p(est.boot, TIMING_LINE, "below")
    p_mismatch = one_sided_p(est.boot, TIMING_LINE, "above")
    return Headline(situation, measure, est, p_match, p_mismatch, order_ci=median_ci_order(values))


def label_headlines(results: list[Headline], alpha: float = ALPHA) -> list[Headline]:
    """Holm's correction over the headline results; sets p_holm and the label of each."""
    reject, adjusted = holm([r.p_directional for r in results], alpha)
    for r, rej, adj in zip(results, reject, adjusted, strict=True):
        r.p_holm = adj
        if r.est.n == 0:
            r.label = NO_DATA
        elif rej:
            r.label = r.direction
        else:
            r.label = CANT_TELL
    return results


# ---- Paired comparisons ----------------------------------------------------------------------------------


def mcnemar(a: Sequence[bool], b: Sequence[bool]) -> dict:
    """McNemar's exact test for paired hits. a and b are hits for the same cases under two conditions."""
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    only_a = int(np.sum(a & ~b))
    only_b = int(np.sum(~a & b))
    n_disc = only_a + only_b
    p = 1.0 if n_disc == 0 else min(1.0, 2 * binom_cdf(min(only_a, only_b), n_disc, 0.5))
    return {
        "n": len(a),
        "only_first": only_a,
        "only_second": only_b,
        "rate_first": float(a.mean()) if len(a) else None,
        "rate_second": float(b.mean()) if len(b) else None,
        "p": p,
    }


def _average_ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="stable")
    ranks = np.empty(len(x), dtype=float)
    xs = x[order]
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def wilcoxon_signed_rank(x: Sequence[float], y: Sequence[float] | None = None) -> dict:
    """Two-sided Wilcoxon signed-rank test on paired differences x - y.

    Zero differences are dropped. Exact (conditional on the observed ranks, so ties are handled) for up to
    60 non-zero differences; normal approximation with tie and continuity corrections beyond that. Pairs
    where the difference is undefined (both errors infinite, or missing) are dropped."""
    x = np.asarray(x, dtype=float)
    with np.errstate(invalid="ignore"):  # inf - inf is undefined: that pair is dropped below
        d = x - (np.asarray(y, dtype=float) if y is not None else 0.0)
    d = d[~np.isnan(d)]
    d = d[d != 0]
    n = len(d)
    out = {"n_used": n, "median_difference": float(np.median(d)) if n else None}
    if n == 0:
        return {**out, "w_plus": 0.0, "p": 1.0}
    ranks = _average_ranks(np.abs(d))
    w_plus = float(ranks[d > 0].sum())
    out["w_plus"] = w_plus
    if n <= 60:
        r2 = np.rint(ranks * 2).astype(int)  # doubled ranks are integers even with ties
        total = int(r2.sum())
        dist = np.zeros(total + 1, dtype=float)
        dist[0] = 1.0
        for r in r2:
            shifted = np.zeros_like(dist)
            shifted[r:] = dist[: total + 1 - r]
            dist = dist + shifted
        dist /= dist.sum()
        w2 = round(w_plus * 2)
        lower = dist[: w2 + 1].sum()
        upper = dist[w2:].sum()
        return {**out, "p": float(min(1.0, 2 * min(lower, upper)))}
    mean = n * (n + 1) / 4.0
    _, counts = np.unique(np.abs(d), return_counts=True)
    var = n * (n + 1) * (2 * n + 1) / 24.0 - float(np.sum(counts**3 - counts)) / 48.0
    if var <= 0:
        return {**out, "p": 1.0}
    diff = w_plus - mean
    z = (abs(diff) - 0.5) / math.sqrt(var)
    return {**out, "p": float(min(1.0, 2 * (1 - normal_cdf(max(z, 0.0)))))}


def sign_flip_test(d: Sequence[float], *, rng: np.random.Generator, n_perm: int = 20_000) -> float:
    """Two-sided test that the mean of d is zero, by flipping the signs of whole units (chains). Exact for
    up to 16 units, Monte Carlo beyond."""
    d = np.asarray(d, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n == 0:
        return float("nan")
    observed = abs(d.mean())
    if n <= 16:
        signs = np.array(list(itertools.product((-1.0, 1.0), repeat=n)))
        stats = np.abs(signs @ d / n)
        return float(np.mean(stats >= observed - 1e-12))
    signs = rng.choice((-1.0, 1.0), size=(n_perm, n))
    stats = np.abs(signs @ d / n)
    return float((1 + np.sum(stats >= observed - 1e-12)) / (1 + n_perm))


# ---- Drift along chains -----------------------------------------------------------------------------------


def drift_halves(
    chains: Sequence,
    steps: Sequence[int],
    misses: Sequence[float],
    chain_lengths: dict | None = None,
    *,
    rng: np.random.Generator,
    n_boot: int = N_BOOT,
) -> dict:
    """Change in error rate from the first half of each chain to the second.

    For every chain with scored steps in both halves, d = (error rate, second half) - (error rate, first
    half). The result is the mean d over chains, a bootstrap range over chains, and a sign-flip test across
    chains. A step is in the first half if step < length / 2, where length is the chain's full number of
    steps (chain_lengths, else the highest scored step + 1)."""
    df = pd.DataFrame({"chain": [str(c) for c in chains], "step": steps, "miss": misses}).dropna()
    rows = []
    for chain, g in df.groupby("chain"):
        length = (chain_lengths or {}).get(chain, int(g["step"].max()) + 1)
        first = g[g["step"] < length / 2]
        second = g[g["step"] >= length / 2]
        if len(first) and len(second):
            rows.append(
                (chain, float(first["miss"].mean()), float(second["miss"].mean()), len(first), len(second))
            )
    if not rows:
        return {"n_chains": 0, "estimate": None, "low": None, "high": None, "p": None}
    d = np.array([r[2] - r[1] for r in rows])
    est = estimate(d, [r[0] for r in rows], None, stat="mean", n_boot=n_boot, rng=rng)
    return {
        "n_chains": len(rows),
        "first_half_error": float(np.mean([r[1] for r in rows])),
        "second_half_error": float(np.mean([r[2] for r in rows])),
        "estimate": est.value,
        "low": est.low,
        "high": est.high,
        "p": sign_flip_test(d, rng=rng),
    }


def conditional_logit_step(groups: Sequence, x: Sequence[float], y: Sequence[float]) -> dict:
    """Logistic regression of error (y = 1) on step number (x), with each chain its own baseline.

    Uses the conditional likelihood (each chain's baseline is conditioned away), which stays unbiased with
    a handful of steps per chain, unlike fitting one intercept per chain. Chains whose steps were all right
    or all wrong carry no information and drop out. Returns the slope per step, its standard error, the
    odds ratio per step and a two-sided Wald p-value."""
    df = pd.DataFrame({"g": [str(v) for v in groups], "x": x, "y": y}).dropna()
    blocks = []
    for _, g in df.groupby("g"):
        xs = g["x"].to_numpy(float)
        ys = g["y"].to_numpy(float).round().astype(int)
        k, m = int(ys.sum()), len(ys)
        if k == 0 or k == m or math.comb(m, k) > 200_000:
            continue
        sums = np.array([xs[list(c)].sum() for c in itertools.combinations(range(m), k)])
        blocks.append((float(xs[ys == 1].sum()), sums))
    if not blocks:
        return {"n_chains_used": 0, "slope": None, "se": None, "odds_ratio": None, "p": None}
    beta = 0.0
    info = 0.0
    for _ in range(100):
        grad, info = 0.0, 0.0
        for s_obs, sums in blocks:
            z = beta * sums
            w = np.exp(z - z.max())
            w /= w.sum()
            mean = float(w @ sums)
            grad += s_obs - mean
            info += float(w @ (sums - mean) ** 2)
        if info <= 0:
            return {"n_chains_used": len(blocks), "slope": None, "se": None, "odds_ratio": None, "p": None}
        step = grad / info
        beta += step
        if abs(beta) > 30:
            break
        if abs(step) < 1e-10:
            break
    se = 1.0 / math.sqrt(info)
    z = beta / se
    return {
        "n_chains_used": len(blocks),
        "slope": beta,
        "se": se,
        "odds_ratio": math.exp(beta) if abs(beta) < 50 else None,
        "p": 2 * (1 - normal_cdf(abs(z))),
    }


# ---- Putting it together ---------------------------------------------------------------------------------


# How cases are grouped for the bootstrap (pre-registered; see the prereg file for why):
#   "agent_in_run"      the plan's wording: agents redrawn within their run (runs kept fixed)
#   "agent_in_scenario" agents redrawn within their scenario
#   "run_in_scenario"   whole runs redrawn within their scenario
#   "two_stage"         runs redrawn within their scenario, then agents within each drawn run
# Chains take the place of agents in the several-steps situation.
CLUSTERING = "two_stage"


def _cluster_columns(
    df: pd.DataFrame, situation: str, scheme: str | None = None
) -> tuple[list, list | None, list | None]:
    """(clusters, strata, top) for the bootstrap of one situation's cases."""
    scheme = scheme or CLUSTERING
    run = df["run_id"].astype(str)
    unit = df["chain_id"].astype(str) if situation == "chain" else run + "/" + df["agent"].astype(str)
    # Strata are the weighting groups: scenario families, with thin families pooled into one group.
    scenario = family_of(df)
    if scheme == "agent_in_run":
        return unit.tolist(), (None if situation == "chain" else run.tolist()), None
    if scheme == "agent_in_scenario":
        return unit.tolist(), scenario.tolist(), None
    if scheme == "run_in_scenario":
        return run.tolist(), scenario.tolist(), None
    if scheme == "two_stage":
        return unit.tolist(), scenario.tolist(), run.tolist()
    raise ValueError(f"unknown clustering scheme {scheme!r}")


def _has_content(scores: pd.DataFrame) -> pd.Series:
    """False for calls whose key facts say nothing beyond "no error" and account names (aud-rules'
    content_facts); those are reported apart from the headline."""
    if "content_facts" not in scores.columns:
        return pd.Series(True, index=scores.index)
    return scores["content_facts"].map(lambda v: True if v is None or pd.isna(v) else bool(v)).astype(bool)


def headline_rows(scores: pd.DataFrame, situation: str, measure: str) -> pd.DataFrame:
    """The cases behind one headline result: test split, main variant, calls that matter whose facts say
    something about what happened. For timing, only commands that really finished (a missing prediction for
    one is an infinite error)."""
    df = scores[
        (scores["split"] == "test")
        & (scores["situation"] == situation)
        & (scores["variant"] == "main")
        & (scores["matters"].fillna(False).astype(bool))
        & _has_content(scores)
    ]
    if measure == "output":
        return df[df["hit"].notna()]
    return df[df["timing_scorable"].fillna(False).astype(bool)]


def _values(df: pd.DataFrame, measure: str) -> np.ndarray:
    return (
        df["hit"].astype(float).to_numpy()
        if measure == "output"
        else df["log_error"].astype(float).to_numpy()
    )


# The headline estimand: every scenario family counts equally, whatever its number of cases (the study
# is about tools in general, not one scenario). The pooled figure, every case counting equally, is shown
# beside it.
WEIGHTING = "family"


def family_of(df: pd.DataFrame) -> pd.Series:
    """Each case's weighting group: its scenario family (variants of a scenario count as one), with thin
    families pooled into one "other" group (``pool_thin_families``); else its scenario."""
    if "wfamily" in df.columns and df["wfamily"].notna().all():
        return df["wfamily"].astype(str)
    if "family" in df.columns and df["family"].notna().all():
        return df["family"].astype(str)
    if "scenario" in df.columns:
        return df["scenario"].astype(str)
    return pd.Series("all", index=df.index)


MIN_RUNS = 2
MIN_CHAINS = 3


def pool_thin_families(scores: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Add the weighting group of every case (column ``wfamily``).

    Rule (decided per situation from the drawn test cases, main form): a scenario family with fewer than
    2 runs among them, or, in the several-steps situation, fewer than 3 chains, is "thin". All thin
    families of a situation are pooled into one group, "other", which gets one equal share and whose runs
    are redrawn together. Returns the scores with the column and, per situation, each group's members
    and counts."""
    out = scores.copy()
    fam = family_of(out.drop(columns=["wfamily"], errors="ignore"))
    out["wfamily"] = fam
    summary: dict[str, list[dict]] = {}
    test = (out["split"] == "test") & (out["variant"] == "main")
    for situation in SITUATIONS:
        rows = out[test & (out["situation"] == situation)]
        if rows.empty:
            continue
        stats = []
        for f, g in rows.groupby(fam[rows.index]):
            n_runs = int(g["run_id"].nunique())
            n_chains = int(g["chain_id"].nunique()) if situation == "chain" else None
            thin = n_runs < MIN_RUNS or (situation == "chain" and (n_chains or 0) < MIN_CHAINS)
            stats.append({"family": f, "runs": n_runs, "chains": n_chains, "cases": len(g), "thin": thin})
        thin = sorted(r["family"] for r in stats if r["thin"])
        group = "other: " + ", ".join(thin) if len(thin) > 1 else (thin[0] if thin else None)
        mask = (out["situation"] == situation) & fam.isin(thin)
        if thin:
            out.loc[mask, "wfamily"] = group
        for r in stats:
            r["group"] = group if r["thin"] else r["family"]
        summary[situation] = stats
    return out, summary


def _headline_for(
    df: pd.DataFrame, situation: str, measure: str, *, rng, n_boot, pooled: bool = True
) -> Headline:
    clusters, strata, top = _cluster_columns(df, situation)
    fam = family_of(df)
    h = headline_test(
        _values(df, measure),
        clusters,
        strata,
        top=top,
        situation=situation,
        measure=measure,
        n_boot=n_boot,
        rng=rng,
        groups=fam.tolist() if WEIGHTING == "family" else None,
    )
    h.n_families = int(fam.nunique())
    if pooled and WEIGHTING == "family" and len(df):
        stat = "mean" if measure == "output" else "median"
        h.pooled = estimate(_values(df, measure), clusters, strata, top, stat=stat, n_boot=n_boot, rng=rng)
    return h


def run_headlines(scores: pd.DataFrame, *, rng: np.random.Generator, n_boot: int = N_BOOT) -> list[Headline]:
    results = []
    for situation in SITUATIONS:
        for measure in MEASURES:
            df = headline_rows(scores, situation, measure)
            results.append(_headline_for(df, situation, measure, rng=rng, n_boot=n_boot))
    return label_headlines(results)


def leave_one_family_out(
    scores: pd.DataFrame, headlines: list[Headline], *, rng: np.random.Generator, n_boot: int = N_BOOT
) -> list[dict]:
    """Each headline result again without one scenario family at a time, with the label it would get:
    its new p-value takes its place among the six in Holm's correction (the other five unchanged)."""
    out = []
    base_p = [h.p_directional for h in headlines]
    for i, h in enumerate(headlines):
        df = headline_rows(scores, h.situation, h.measure)
        fam = family_of(df)
        for dropped in sorted(fam.unique()):
            sub = df[fam != dropped]
            row = {
                "situation": h.situation,
                "measure": h.measure,
                "dropped": dropped,
                "n_dropped": int((fam == dropped).sum()),
                "full_label": h.label,
            }
            if sub.empty:
                out.append(
                    {
                        **row,
                        "estimate": None,
                        "low": None,
                        "high": None,
                        "n": 0,
                        "label": NO_DATA,
                        "flipped": h.label != NO_DATA,
                    }
                )
                continue
            h2 = _headline_for(sub, h.situation, h.measure, rng=rng, n_boot=n_boot, pooled=False)
            p = list(base_p)
            p[i] = h2.p_directional
            reject, _ = holm(p)
            label = h2.direction if reject[i] else CANT_TELL
            out.append(
                {
                    **row,
                    "estimate": _clean(h2.est.value),
                    "low": _clean(h2.est.low),
                    "high": _clean(h2.est.high),
                    "n": h2.est.n,
                    "label": label,
                    "flipped": label != h.label,
                }
            )
    return out


@dataclass
class Part:
    """One secondary result."""

    group: str
    name: str
    measure: str  # "output", "timing", "rate", "difference", ...
    values: dict
    p: float | None = None
    p_bh: float | None = None
    significant: bool | None = None
    situation: str | None = None
    subset: str | None = None

    def as_dict(self) -> dict:
        return {
            "group": self.group,
            "name": self.name,
            "measure": self.measure,
            "situation": self.situation,
            "subset": self.subset,
            **{k: (_clean(v) if isinstance(v, float) else v) for k, v in self.values.items()},
            "p": _clean(self.p),
            "p_bh": _clean(self.p_bh),
            "significant": self.significant,
        }


def _two_sided_against_line(est: Estimate, measure: str) -> float:
    if est.n == 0:
        return float("nan")
    line = OUTPUT_LINE if measure == "output" else TIMING_LINE
    return min(1.0, 2 * min(one_sided_p(est.boot, line, "above"), one_sided_p(est.boot, line, "below")))


def _subset_parts(
    scores: pd.DataFrame, situation: str, by: str, *, rng: np.random.Generator, n_boot: int
) -> list[Part]:
    parts = []
    for measure in MEASURES:
        base = headline_rows(scores, situation, measure)
        if by not in base.columns:
            continue
        for value, df in base.groupby(base[by].fillna("unknown").astype(str)):
            clusters, strata, top = _cluster_columns(df, situation)
            stat = "mean" if measure == "output" else "median"
            est = estimate(_values(df, measure), clusters, strata, top, stat=stat, n_boot=n_boot, rng=rng)
            parts.append(
                Part(
                    f"by {by.replace('_', ' ')}",
                    f"{SITUATION_NAMES[situation]}: {value}",
                    measure,
                    est.as_dict(),
                    _two_sided_against_line(est, measure),
                    situation=situation,
                    subset=value,
                )
            )
    return parts


def _rate_part(group, name, df, flag_col, situation, *, rng, n_boot) -> Part | None:
    df = df[df[flag_col].notna()]
    if df.empty:
        return None
    clusters, strata, top = _cluster_columns(df, situation)
    est = estimate(df[flag_col].astype(float).to_numpy(), clusters, strata, top, n_boot=n_boot, rng=rng)
    return Part(group, name, "rate", est.as_dict())


def _pair(scores: pd.DataFrame, situation: str, variant: str) -> pd.DataFrame:
    """Main answers paired with another variant of the same command (test split), matched on the key."""
    s = scores[(scores["split"] == "test") & (scores["situation"] == situation)]
    main = s[s["variant"] == "main"].drop_duplicates("key")
    other = s[s["variant"] == variant].drop_duplicates("key")
    return main.merge(other, on="key", suffixes=("_main", "_other"))


def _two_sided_zero(est: Estimate) -> float:
    """Two-sided p-value for "no difference" from the clustered bootstrap. Several pairs can come from one
    chain or one agent, which McNemar's and Wilcoxon's tests treat as independent; this p-value doesn't, so
    it is the one tested. The two classic tests are reported beside it."""
    if est.n == 0 or not len(est.boot):
        return float("nan")
    return min(1.0, 2 * min(one_sided_p(est.boot, 0.0, "above"), one_sided_p(est.boot, 0.0, "below")))


def _pair_clusters(pairs: pd.DataFrame, situation: str) -> tuple[list, list | None, list | None]:
    """Clusters for paired cases, as for single cases (the chain for chain steps)."""
    df = pd.DataFrame(
        {
            "run_id": pairs["run_id_main"],
            "agent": pairs["agent_main"],
            "scenario": pairs["scenario_main"] if "scenario_main" in pairs.columns else "all",
            "family": pairs["family_main"] if "family_main" in pairs.columns else None,
            "wfamily": pairs["wfamily_main"] if "wfamily_main" in pairs.columns else None,
            "chain_id": pairs["chain_id_main"].where(pairs["chain_id_main"].notna(), pairs["chain_id_other"]),
        }
    )
    return _cluster_columns(df, situation)


def _paired_parts(
    group: str,
    situation: str,
    label_main: str,
    label_other: str,
    pairs: pd.DataFrame,
    *,
    rng,
    n_boot,
    matters_only=True,
) -> list[Part]:
    """Same commands under two conditions. Output: McNemar's test, and the difference in the share of
    hits with a clustered range. Timing: Wilcoxon's test, and the median paired difference in log error
    with a clustered range (positive: the first condition is further off)."""
    parts: list[Part] = []
    if pairs.empty:
        return parts
    if matters_only:
        pairs = pairs[pairs["matters_main"].fillna(False).astype(bool)]
    out = pairs[pairs["hit_main"].notna() & pairs["hit_other"].notna()]
    if len(out):
        mc = mcnemar(out["hit_main"].astype(bool), out["hit_other"].astype(bool))
        clusters, strata, top = _pair_clusters(out, situation)
        diff = estimate(
            out["hit_main"].astype(float).to_numpy() - out["hit_other"].astype(float).to_numpy(),
            clusters,
            strata,
            top,
            n_boot=n_boot,
            rng=rng,
        )
        parts.append(
            Part(
                group,
                f"Share of hits: {label_main} minus {label_other}",
                "difference",
                {**diff.as_dict(), **{k: v for k, v in mc.items() if k != "p"}, "mcnemar_p": mc["p"]},
                _two_sided_zero(diff),
                situation=situation,
                subset="output",
            )
        )
    tim = pairs[
        pairs["timing_scorable_main"].fillna(False).astype(bool)
        & pairs["timing_scorable_other"].fillna(False).astype(bool)
    ]
    if len(tim):
        wx = wilcoxon_signed_rank(tim["log_error_main"], tim["log_error_other"])
        d = tim["log_error_main"].astype(float).to_numpy() - tim["log_error_other"].astype(float).to_numpy()
        keep = ~np.isnan(d)
        clusters, strata, top = _pair_clusters(tim[keep], situation)
        diff = estimate(d[keep], clusters, strata, top, stat="median", n_boot=n_boot, rng=rng)
        parts.append(
            Part(
                group,
                f"Timing error: {label_main} minus {label_other} (log scale)",
                "paired timing",
                {
                    **diff.as_dict(),
                    "median_error_first": float(np.median(tim["log_error_main"])),
                    "median_error_second": float(np.median(tim["log_error_other"])),
                    "n_used": wx["n_used"],
                    "wilcoxon_p": wx["p"],
                },
                _two_sided_zero(diff),
                situation=situation,
                subset="timing",
            )
        )
    return parts


def run_parts(
    scores: pd.DataFrame,
    *,
    yardstick: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
    contradictions: pd.DataFrame | None = None,
    rng: np.random.Generator,
    n_boot: int = N_BOOT,
) -> list[Part]:
    parts: list[Part] = []
    test = scores[scores["split"] == "test"]

    for situation in SITUATIONS:
        parts += _subset_parts(scores, situation, "scenario", rng=rng, n_boot=n_boot)
        parts += _subset_parts(scores, situation, "tool_kind", rng=rng, n_boot=n_boot)

    for situation in SITUATIONS:
        name = SITUATION_NAMES[situation]
        base = headline_rows(scores, situation, "output")
        if "has_verdict" in base.columns:
            vdf = base[base["has_verdict"].fillna(False).astype(bool)]
            if len(vdf):
                clusters, strata, top = _cluster_columns(vdf, situation)
                est = estimate(
                    vdf["hit"].astype(float).to_numpy(), clusters, strata, top, n_boot=n_boot, rng=rng
                )
                parts.append(
                    Part(
                        "verdicts",
                        f"{name}: pass-or-fail verdicts only",
                        "output",
                        est.as_dict(),
                        _two_sided_against_line(est, "output"),
                    )
                )
        fp = base[base["real_verdict"] == "fail"] if "real_verdict" in base.columns else base.iloc[0:0]
        p = _rate_part(
            "false passes",
            f"{name}: said it passed when it really failed",
            fp,
            "false_pass",
            situation,
            rng=rng,
            n_boot=n_boot,
        )
        if p:
            parts.append(p)
        rows = test[
            (test["situation"] == situation)
            & (test["variant"] == "main")
            & (test["matters"].fillna(False).astype(bool))
        ]
        p = _rate_part(
            "time band",
            f"{name}: right time band (seconds / minutes / never)",
            rows,
            "band_right",
            situation,
            rng=rng,
            n_boot=n_boot,
        )
        if p:
            parts.append(p)
        if len(rows):
            parts.append(
                Part(
                    "time band",
                    f"{name}: share that never really finished",
                    "rate",
                    {"estimate": float((rows["real_band"] == "never").mean()), "n": len(rows)},
                )
            )
        tim = headline_rows(scores, situation, "timing")
        signed = tim["log_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
        if len(signed):
            parts.append(
                Part(
                    "timing bias",
                    f"{name}: typical predicted / real time",
                    "factor",
                    {"estimate": float(math.exp(np.median(signed))), "n": len(signed)},
                )
            )
        if situation == "shared" and "wait_right" in rows.columns:
            p = _rate_part(
                "waiting",
                f"{name}: said correctly whether it would wait",
                rows,
                "wait_right",
                situation,
                rng=rng,
                n_boot=n_boot,
            )
            if p:
                parts.append(p)

    # Sensitivity: timing including commands timed only to the end of a turn with several commands.
    if "timing_finished" in test.columns:
        for situation in SITUATIONS:
            rows = test[
                (test["situation"] == situation)
                & (test["variant"] == "main")
                & test["matters"].fillna(False).astype(bool)
                & test["timing_finished"].fillna(False).astype(bool)
            ]
            n_extra = int(rows["shared_turn_timing"].fillna(False).astype(bool).sum())
            if rows.empty or n_extra == 0:
                continue
            clusters, strata, top = _cluster_columns(rows, situation)
            est = estimate(
                rows["log_error"].astype(float).to_numpy(),
                clusters,
                strata,
                top,
                stat="median",
                n_boot=n_boot,
                rng=rng,
            )
            parts.append(
                Part(
                    "timing sensitivity",
                    f"{SITUATION_NAMES[situation]}: timing including {n_extra} commands timed to the end of "
                    "a several-command turn",
                    "timing",
                    est.as_dict(),
                    situation=situation,
                )
            )

    # Calls whose facts carry no content: reported apart from the headline.
    if "content_facts" in test.columns:
        for situation in SITUATIONS:
            rows = test[
                (test["situation"] == situation)
                & (test["variant"] == "main")
                & test["matters"].fillna(False).astype(bool)
                & ~_has_content(test)
                & test["hit"].notna()
            ]
            if len(rows):
                clusters, strata, top = _cluster_columns(rows, situation)
                est = estimate(
                    rows["hit"].astype(float).to_numpy(), clusters, strata, top, n_boot=n_boot, rng=rng
                )
                parts.append(
                    Part(
                        "facts without content",
                        f'{SITUATION_NAMES[situation]}: calls whose facts are only "no error" and account names',
                        "output",
                        est.as_dict(),
                        situation=situation,
                    )
                )

    # The content-free yardstick: what an answer that knows nothing about the command scores.
    if "content_free_hit" in test.columns:
        for situation in SITUATIONS:
            base = headline_rows(scores, situation, "output")
            rows = base[base["content_free_hit"].notna()]
            if rows.empty:
                continue
            clusters, strata, top = _cluster_columns(rows, situation)
            est = estimate(
                rows["content_free_hit"].astype(float).to_numpy(),
                clusters,
                strata,
                top,
                n_boot=n_boot,
                rng=rng,
                groups=family_of(rows).tolist() if WEIGHTING == "family" else None,
            )
            parts.append(
                Part(
                    "content-free yardstick",
                    f"{SITUATION_NAMES[situation]}: all scenarios",
                    "output",
                    est.as_dict(),
                    situation=situation,
                    subset="all",
                )
            )
            for fam, g in rows.groupby(family_of(rows)):
                parts.append(
                    Part(
                        "content-free yardstick",
                        f"{SITUATION_NAMES[situation]}: {fam}",
                        "output",
                        {"estimate": float(g["content_free_hit"].mean()), "n": len(g)},
                        situation=situation,
                        subset=fam,
                    )
                )

    # Calls that don't matter (one step).
    other = test[
        (test["situation"] == "one_step")
        & (test["variant"] == "main")
        & ~(test["matters"].fillna(False).astype(bool))
    ]
    for measure in MEASURES:
        df = (
            other[other["hit"].notna()]
            if measure == "output"
            else other[other["timing_scorable"].fillna(False).astype(bool)]
        )
        if len(df):
            clusters, strata, top = _cluster_columns(df, "one_step")
            est = estimate(
                _values(df, measure),
                clusters,
                strata,
                top,
                stat="mean" if measure == "output" else "median",
                n_boot=n_boot,
                rng=rng,
            )
            parts.append(
                Part(
                    "calls that don't matter",
                    "One step: calls that don't matter",
                    measure,
                    est.as_dict(),
                    _two_sided_against_line(est, measure),
                )
            )

    # Paired comparisons.
    parts += _paired_parts(
        "own past against real past",
        "chain",
        "real past",
        "own past",
        _swap(_pair(scores, "chain", "real_past")),
        rng=rng,
        n_boot=n_boot,
    )
    parts += _paired_parts(
        "record of the others",
        "shared",
        "with the record",
        "without it",
        _pair(scores, "shared", "no_record"),
        rng=rng,
        n_boot=n_boot,
    )
    parts += _paired_parts(
        "long history",
        "one_step",
        "long history",
        "short history",
        _swap(_pair(scores, "one_step", "long_history")),
        rng=rng,
        n_boot=n_boot,
        matters_only=False,
    )

    # Self-consistency: the same case asked twice.
    for situation in SITUATIONS:
        pairs = _pair(scores, situation, "repeat")
        both = pairs[pairs["hit_main"].notna() & pairs["hit_other"].notna()]
        if len(both):
            same_hit = float((both["hit_main"] == both["hit_other"]).mean())
            same_text = float(
                (
                    both["predicted_output_main"].fillna("").str.strip()
                    == both["predicted_output_other"].fillna("").str.strip()
                ).mean()
            )
            parts.append(
                Part(
                    "self-consistency",
                    f"{SITUATION_NAMES[situation]}: same case asked twice",
                    "rate",
                    {"same_hit": same_hit, "same_text": same_text, "n": len(both)},
                )
            )

    # Chains: drift and steps before the first miss.
    chain = test[(test["situation"] == "chain") & (test["variant"] == "main")]
    if len(chain):
        lengths = chain.groupby(chain["chain_id"].astype(str))["step"].max().add(1).to_dict()
        for label, df in (
            ("calls that matter", chain[chain["matters"].fillna(False).astype(bool)]),
            ("all steps", chain),
        ):
            df = df[df["hit"].notna()]
            if df.empty:
                continue
            miss = 1.0 - df["hit"].astype(float)
            dh = drift_halves(df["chain_id"], df["step"], miss, lengths, rng=rng, n_boot=n_boot)
            parts.append(
                Part(
                    "drift",
                    f"Error rate, second half of chain minus first half ({label})",
                    "difference",
                    {k: v for k, v in dh.items() if k != "p"},
                    dh["p"] if label == "all steps" else None,
                )
            )
            cl = conditional_logit_step(df["chain_id"], df["step"], miss)
            parts.append(
                Part(
                    "drift",
                    f"Logistic check: odds of an error per step ({label})",
                    "odds ratio",
                    {k: v for k, v in cl.items() if k != "p"},
                    cl["p"] if label == "all steps" else None,
                )
            )
        if "after_miss" in chain.columns:
            m = chain[chain["matters"].fillna(False).astype(bool) & chain["hit"].notna()]
            clean = m[~m["after_miss"].fillna(False).astype(bool)]
            if len(clean):
                est = estimate(
                    clean["hit"].astype(float).to_numpy(),
                    clean["chain_id"].astype(str).tolist(),
                    None,
                    n_boot=n_boot,
                    rng=rng,
                )
                parts.append(
                    Part(
                        "drift",
                        "Several steps: hits counting only steps before the chain's first miss",
                        "output",
                        est.as_dict(),
                    )
                )

    if contradictions is not None:
        n_chains = int(chain["chain_id"].nunique()) if len(chain) else 0
        confirmed = (
            contradictions[
                contradictions.get("confirmed", pd.Series(dtype=object)).fillna(False).astype(bool)
            ]
            if "confirmed" in contradictions.columns
            else None
        )
        parts.append(
            Part(
                "self-contradiction",
                "Contradiction candidates found by the rules",
                "count",
                {
                    "candidates": len(contradictions),
                    "chains_with_candidates": int(contradictions["chain_id"].nunique())
                    if len(contradictions)
                    else 0,
                    "confirmed_by_hand": None if confirmed is None else len(confirmed),
                    "n_chains": n_chains,
                },
            )
        )

    # Auditor against the rule of thumb (timing).
    if yardstick is not None and len(yardstick):
        ys = yardstick[["key", "rule_seconds"]].dropna()
        for situation in SITUATIONS:
            tim = headline_rows(scores, situation, "timing").merge(ys, on="key")
            if tim.empty:
                continue
            rule_err = np.abs(
                np.log(
                    np.maximum(tim["rule_seconds"].astype(float), 1.0)
                    / np.maximum(tim["real_seconds"].astype(float), 1.0)
                )
            )
            wx = wilcoxon_signed_rank(tim["log_error"], rule_err)
            parts.append(
                Part(
                    "rule of thumb",
                    f"{SITUATION_NAMES[situation]}: auditor's timing error against the rule of thumb",
                    "paired timing",
                    {
                        "n": len(tim),
                        "median_error_first": float(np.median(tim["log_error"])),
                        "median_error_second": float(np.median(rule_err)),
                        "n_used": wx["n_used"],
                    },
                    wx["p"],
                )
            )

    if queue is not None and len(queue):
        parts += _queue_parts(queue)

    reject, adjusted = benjamini_hochberg([np.nan if p.p is None else p.p for p in parts])
    for p, rej, adj in zip(parts, reject, adjusted, strict=True):
        if p.p is not None and not math.isnan(p.p):
            p.p_bh, p.significant = adj, rej
    return parts


def _swap(pairs: pd.DataFrame) -> pd.DataFrame:
    """Swap the _main and _other suffixes, so the variant is reported first."""
    if pairs.empty:
        return pairs
    ren = {}
    for c in pairs.columns:
        if c.endswith("_main"):
            ren[c] = c[: -len("_main")] + "_other"
        elif c.endswith("_other"):
            ren[c] = c[: -len("_other")] + "_main"
    return pairs.rename(columns=ren)


def score_queue(queue: pd.DataFrame) -> pd.DataFrame:
    """Errors of the waiting-line forecasts, for the auditor and (when present) the checker program.
    Columns needed: real_typical_wait_s, real_waiting_5min, real_waiting_10min, real_hits_limit and the
    auditor's typical_wait_s, waiting_5min, waiting_10min, hits_limit; sim_* for the program."""
    q = queue.copy()

    def wait_err(pred):
        return np.abs(
            np.log(
                np.maximum(pred.astype(float), 1.0) / np.maximum(q["real_typical_wait_s"].astype(float), 1.0)
            )
        )

    q["auditor_wait_error"] = wait_err(q["typical_wait_s"]) if "typical_wait_s" in q else np.nan
    for who, prefix in (("auditor", ""), ("program", "sim_")):
        for h in ("5min", "10min"):
            col = f"{prefix}waiting_{h}"
            q[f"{who}_waiting_{h}_error"] = (
                (q[col].astype(float) - q[f"real_waiting_{h}"].astype(float)).abs() if col in q else np.nan
            )
        col = f"{prefix}hits_limit"
        q[f"{who}_limit_right"] = (
            (q[col].astype("boolean") == q["real_hits_limit"].astype("boolean")).astype(float)
            if col in q
            else np.nan
        )
    q["program_wait_error"] = wait_err(q["sim_typical_wait_s"]) if "sim_typical_wait_s" in q else np.nan
    return q


def _queue_parts(queue: pd.DataFrame) -> list[Part]:
    q = score_queue(queue)
    q = q[q.get("split", pd.Series("test", index=q.index)).fillna("test") == "test"]
    parts = []
    vals = {"n": len(q)}
    for who in ("auditor", "program"):
        e = q[f"{who}_wait_error"].dropna()
        if len(e):
            vals[f"{who}_typical_wait_factor"] = float(math.exp(np.median(e)))
        for h in ("5min", "10min"):
            e = q[f"{who}_waiting_{h}_error"].dropna()
            if len(e):
                vals[f"{who}_waiting_{h}_median_abs_error"] = float(np.median(e))
        e = q[f"{who}_limit_right"].dropna()
        if len(e):
            vals[f"{who}_limit_right"] = float(e.mean())
    p = None
    both = q[["auditor_wait_error", "program_wait_error"]].dropna()
    if len(both):
        p = wilcoxon_signed_rank(both["auditor_wait_error"], both["program_wait_error"])["p"]
    parts.append(
        Part(
            "waiting-line forecasts",
            "Proof conference only: typical wait over the next 10 minutes, auditor against the checker program",
            "forecast",
            vals,
            p,
        )
    )
    return parts


def error_by_step(scores: pd.DataFrame, *, rng: np.random.Generator, n_boot: int = N_BOOT) -> dict:
    """Error rate at each chain step (test split, main variant), with ranges from redrawing whole chains.
    Two versions: calls that matter, and all steps."""
    chain = scores[
        (scores["split"] == "test")
        & (scores["situation"] == "chain")
        & (scores["variant"] == "main")
        & scores["hit"].notna()
    ]
    out: dict[str, list[dict]] = {}
    for label, df in (
        ("calls that matter", chain[chain["matters"].fillna(False).astype(bool)]),
        ("all steps", chain),
    ):
        rows = []
        for step, g in df.groupby("step"):
            est = estimate(
                1.0 - g["hit"].astype(float).to_numpy(),
                g["chain_id"].astype(str).tolist(),
                None,
                n_boot=n_boot,
                rng=rng,
            )
            rows.append({"step": int(step), **est.as_dict()})
        out[label] = rows
    return out


def counts(scores: pd.DataFrame) -> list[dict]:
    """How many cases were drawn, answered, and parsed, per split, situation and variant."""
    out = []
    for (split, situation, variant), g in scores.groupby(["split", "situation", "variant"], dropna=False):
        out.append(
            {
                "split": split,
                "situation": situation,
                "variant": variant,
                "drawn": len(g),
                "answered": int(g["answered"].fillna(False).astype(bool).sum()),
                "not_run": int(g["not_run"].fillna(False).astype(bool).sum()) if "not_run" in g else 0,
                "parsed": int(g["parse_ok"].fillna(False).astype(bool).sum()),
                "matters": int(g["matters"].fillna(False).astype(bool).sum()),
                "output_scorable": int(g["hit"].notna().sum()),
                "timing_scorable": int(g["timing_scorable"].fillna(False).astype(bool).sum()),
            }
        )
    return out


def run_analysis(
    scores: pd.DataFrame,
    *,
    yardstick: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
    contradictions: pd.DataFrame | None = None,
    seed: int = SEED,
    n_boot: int = N_BOOT,
) -> dict:
    """The whole analysis, as a JSON-able dict the report renders."""
    rng = np.random.default_rng(seed)
    pooling: dict = {}
    if WEIGHTING == "family":
        scores, pooling = pool_thin_families(scores)
    headlines = run_headlines(scores, rng=rng, n_boot=n_boot)
    loo = leave_one_family_out(scores, headlines, rng=rng, n_boot=n_boot)
    parts = run_parts(
        scores, yardstick=yardstick, queue=queue, contradictions=contradictions, rng=rng, n_boot=n_boot
    )
    return {
        "settings": {
            "output_line": OUTPUT_LINE,
            "timing_line_factor": 2.0,
            "alpha": ALPHA,
            "bh_q": BH_Q,
            "n_boot": n_boot,
            "clustering": CLUSTERING,
            "weighting": WEIGHTING,
            "seed": seed,
            "level": LEVEL,
        },
        "counts": counts(scores),
        "headline": [h.as_dict() for h in headlines],
        "parts": [p.as_dict() for p in parts],
        "error_by_step": error_by_step(scores, rng=rng, n_boot=n_boot),
        "leave_one_family_out": loo,
        "pooling": pooling,
    }
