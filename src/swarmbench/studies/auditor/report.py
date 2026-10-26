"""The results report for the auditor prediction study: a plain-language Markdown page with figures.

    uv sync --group studies          # matplotlib, for the figures
    uv run python -m swarmbench.studies.auditor.report --batch test

Reads the shared data folder, scores the answers (score.py), runs the statistics (analysis.py), and writes
report_<batch>.md, analysis_<batch>.json and the figures (PNG and SVG) to runs/_studies/auditor/report_<batch>/.
`--simulated` builds the same report from simulated data with a known truth, to check the look.

matplotlib is imported only inside the figure code, so the rest of the study runs without it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from swarmbench.studies.auditor import analysis as an
from swarmbench.studies.auditor import score as sc

# Colourblind-safe categorical slots (the first three validate as a set), with a marker shape each so the
# figures also read in black and white.
SERIES = [("#2a78d6", "o"), ("#eb6834", "s"), ("#1baf7a", "^")]
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3de"
LINE = "#52514e"

SCHEME_TEXT = {
    "two_stage": "runs redrawn within their scenario, then agents within each run; whole chains in place of "
    "agents for several steps",
    "agent_in_run": "agents redrawn within their run; whole chains for several steps",
    "agent_in_scenario": "agents redrawn within their scenario; whole chains for several steps",
    "run_in_scenario": "whole runs redrawn within their scenario",
}
VARIANT_NAMES = {
    "main": "main",
    "real_past": "asked with the real past",
    "no_record": "without the record of others",
    "long_history": "with a long history",
    "repeat": "asked a second time",
}


@dataclass
class Figure:
    name: str
    title: str
    caption: str


# ---- Formatting ---------------------------------------------------------------------------------------------


def pct(x) -> str:
    return "–" if x is None else f"{100 * x:.0f}%"


def factor(x) -> str:
    if x is None:
        return "–"
    if not math.isfinite(x):
        return "∞"
    return f"{x:.2f}×" if x < 10 else f"{x:.0f}×"


def _exp(x):
    if x is None:
        return None
    return math.exp(x) if x < 700 else math.inf


def headline_cell(h: dict) -> str:
    if h["n"] == 0:
        return "no data"
    if h["measure"] == "output":
        value = f"{pct(h['estimate'])} hits ({pct(h['low'])} to {pct(h['high'])})"
    else:
        value = (
            f"{factor(h.get('factor'))} off ({factor(h.get('factor_low'))} to {factor(h.get('factor_high'))})"
        )
    return f"**{h['label']}**<br>{value}<br>{h['n']} cases, {h['n_clusters']} {_unit(h['situation'])}"


def _unit(situation: str) -> str:
    return "chains" if situation == "chain" else "agents"


def format_part_value(p: dict) -> tuple[str, str]:
    """(estimate, range) as text for one part."""
    m = p["measure"]
    est, lo, hi = p.get("estimate"), p.get("low"), p.get("high")
    rng = ""
    if m in ("output", "rate"):
        if lo is not None:
            rng = f"{pct(lo)} to {pct(hi)}"
        if est is None and "same_hit" in p:
            return f"same hit/miss {pct(p['same_hit'])}, same text {pct(p['same_text'])}", ""
        return pct(est), rng
    if m == "timing":
        return factor(_exp(est)) + " off", (
            f"{factor(_exp(lo))} to {factor(_exp(hi))}" if lo is not None else ""
        )
    if m == "difference":
        if est is None:
            return "–", ""
        rng = f"{100 * lo:+.0f} to {100 * hi:+.0f} points" if lo is not None else ""
        return f"{100 * est:+.0f} points", rng
    if m == "paired timing":
        if est is None:
            return (
                f"{factor(_exp(p.get('median_error_first')))} vs {factor(_exp(p.get('median_error_second')))} off",
                "",
            )
        return (
            f"{factor(_exp(p.get('median_error_first')))} vs {factor(_exp(p.get('median_error_second')))} off",
            f"paired difference {factor(_exp(est))} ({factor(_exp(lo))} to {factor(_exp(hi))})",
        )
    if m == "odds ratio":
        return ("–" if p.get("odds_ratio") is None else f"{p['odds_ratio']:.2f} per step"), ""
    if m == "factor":
        return factor(est), ""
    keys = [
        k
        for k in p
        if k not in ("group", "name", "measure", "situation", "subset", "p", "p_bh", "significant")
    ]
    return ", ".join(f"{k.replace('_', ' ')} {_short(p[k])}" for k in keys if p[k] is not None), ""


def _short(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _p_text(p: dict) -> str:
    if p.get("p_bh") is None:
        return ""
    star = " (significant)" if p.get("significant") else ""
    return f"{p['p_bh']:.3f}{star}"


# ---- Figures ------------------------------------------------------------------------------------------------


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.size": 9.5,
            "axes.edgecolor": INK_2,
            "axes.labelcolor": INK,
            "axes.titlesize": 10.5,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "legend.frameon": False,
            "svg.fonttype": "none",
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    return plt


def _save(fig, out_dir: Path, name: str) -> None:
    fig.savefig(out_dir / f"{name}.png", dpi=200, bbox_inches="tight")
    fig.savefig(out_dir / f"{name}.svg", bbox_inches="tight")


def _err(est, lo, hi):
    return np.array([[max(0.0, est - lo)], [max(0.0, hi - est)]])


def fig_headline(results: dict, out_dir: Path) -> Figure | None:
    plt = _plt()
    hs = results["headline"]
    if not any(h["n"] for h in hs):
        return None
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.0), sharey=True, gridspec_kw={"wspace": 0.42})
    for ax, measure in zip(axes, an.MEASURES, strict=True):
        rows = [h for h in hs if h["measure"] == measure]
        for i, h in enumerate(rows):
            y = len(rows) - 1 - i
            color, marker = SERIES[i]
            if h["n"] == 0:
                ax.text(
                    0.5,
                    y,
                    "no data",
                    transform=ax.get_yaxis_transform(),
                    ha="center",
                    va="center",
                    color=INK_2,
                )
                continue
            if measure == "output":
                est, lo, hi = 100 * h["estimate"], 100 * h["low"], 100 * h["high"]
            else:
                est, lo, hi = h["factor"], h["factor_low"], h["factor_high"]
                hi = min(hi, 1e3) if hi is not None else hi
            ax.errorbar(
                est,
                y,
                xerr=_err(est, lo, hi),
                fmt=marker,
                color=color,
                ms=7,
                elinewidth=2,
                capsize=4,
                capthick=2,
            )
            # The label sits in a column right of the panel, so it never collides with the bars.
            ax.text(
                1.03,
                y,
                h["label"],
                transform=ax.get_yaxis_transform(),
                va="center",
                color=INK,
                fontsize=9,
                fontweight="bold" if h["label"] != an.CANT_TELL else "normal",
            )
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([an.SITUATION_NAMES[h["situation"]] for h in reversed(rows)])
        ax.set_ylim(-0.6, len(rows) - 0.4)
        if measure == "timing":
            ax.tick_params(labelleft=False)
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        if measure == "output":
            ax.axvline(80, color=LINE, ls="--", lw=1.2)
            ax.text(80, len(rows) - 0.45, " line: 80%", color=INK_2, fontsize=8.5, va="bottom")
            ax.set_xlim(0, 100)
            ax.set_xlabel("Calls that matter with every key fact right (%)")
            ax.set_title("Output")
        else:
            ax.set_xscale("log")
            ax.axvline(2, color=LINE, ls="--", lw=1.2)
            ax.text(2, len(rows) - 0.45, " line: 2× off", color=INK_2, fontsize=8.5, va="bottom")
            finite = [
                h["factor_high"]
                for h in rows
                if h["n"] and h.get("factor_high") and math.isfinite(h["factor_high"])
            ]
            ax.set_xlim(1, max([4.0] + [f * 1.6 for f in finite]))
            ax.set_xlabel("Typical timing error (times too fast or too slow, log scale)")
            ax.set_title("Timing")
            _log_ticks(ax)
    _save(fig, out_dir, "headline")
    plt.close(fig)
    n_text = "; ".join(
        f"{an.SITUATION_NAMES[h['situation']].lower()}: {h['n']} cases from {h['n_clusters']} {_unit(h['situation'])}"
        for h in hs
        if h["measure"] == "output" and h["n"]
    )
    return Figure(
        "headline",
        "The six headline results",
        "Dots are estimates; bars are 95% intervals from the bootstrap "
        f"({SCHEME_TEXT[results['settings']['clustering']]}). Labels come from one-sided tests against the "
        f"dashed lines, corrected together with Holm's method. Output cases: {n_text}. Timing covers the "
        "commands that really finished.",
    )


NICE_FACTORS = (0.1, 0.2, 0.25, 0.5, 0.67, 0.8, 1, 1.25, 1.5, 2, 3, 4, 6, 10, 20, 50, 100, 300, 1000)


def _log_ticks(ax, axis: str = "x") -> None:
    """Plain "2×" tick labels at a few round factors on a log axis, and no minor labels."""
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullFormatter, NullLocator

    a = ax.xaxis if axis == "x" else ax.yaxis
    ax.autoscale_view()
    lo, hi = ax.get_xlim() if axis == "x" else ax.get_ylim()
    ticks = [t for t in NICE_FACTORS if lo <= t <= hi]
    if len(ticks) > 7:
        ticks = [t for t in ticks if t in (0.1, 0.25, 0.5, 1, 1.5, 2, 4, 10, 50, 300, 1000)]
    a.set_major_locator(FixedLocator(ticks))
    a.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}×"))
    a.set_minor_locator(NullLocator())
    a.set_minor_formatter(NullFormatter())


def _log_seconds(ax) -> None:
    """Plain-number tick labels (1, 10, 100 ...) on both log axes of a seconds-against-seconds plot."""
    from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

    for a in (ax.xaxis, ax.yaxis):
        a.set_major_locator(LogLocator(base=10))
        a.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
        a.set_minor_formatter(NullFormatter())


def fig_subsets(results: dict, out_dir: Path, by: str) -> Figure | None:
    """Per scenario or per kind of tool: one row per subset, one dodged series per situation."""
    group = f"by {by.replace('_', ' ')}"
    parts = [p for p in results["parts"] if p["group"] == group and p.get("estimate") is not None]
    if not parts:
        return None
    plt = _plt()
    subsets = sorted({p["subset"] for p in parts})
    fig, axes = plt.subplots(
        1, 2, figsize=(9.2, 0.45 * len(subsets) + 1.6), gridspec_kw={"wspace": 0.35}, sharey=True
    )
    present = [s for s in an.SITUATIONS if any(p["situation"] == s for p in parts)]
    offsets = np.linspace(0.22, -0.22, len(present)) if len(present) > 1 else [0.0]
    for ax, measure in zip(axes, an.MEASURES, strict=True):
        for k, situation in enumerate(present):
            color, marker = SERIES[an.SITUATIONS.index(situation)]
            for p in parts:
                if p["measure"] != measure or p["situation"] != situation:
                    continue
                y = len(subsets) - 1 - subsets.index(p["subset"]) + offsets[k]
                if measure == "output":
                    est, lo, hi = 100 * p["estimate"], 100 * p["low"], 100 * p["high"]
                else:
                    est, lo, hi = (_exp(p["estimate"]), _exp(p["low"]), _exp(p["high"]))
                    hi = min(hi, 1e3)
                ax.errorbar(
                    est,
                    y,
                    xerr=_err(est, lo, hi),
                    fmt=marker,
                    color=color,
                    ms=5.5,
                    elinewidth=1.6,
                    capsize=2.5,
                    label=an.SITUATION_NAMES[situation],
                )
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        if measure == "output":
            ax.axvline(80, color=LINE, ls="--", lw=1.1)
            ax.set_xlim(0, 100)
            ax.set_xlabel("Hits among calls that matter (%)")
            ax.set_title("Output")
        else:
            ax.set_xscale("log")
            ax.axvline(2, color=LINE, ls="--", lw=1.1)
            ax.set_xlabel("Typical timing error (times off, log scale)")
            ax.set_title("Timing")
            _log_ticks(ax)
    axes[0].set_yticks(range(len(subsets)))
    axes[0].set_yticklabels(list(reversed([s.replace("_", " ") for s in subsets])))
    handles, labels = axes[0].get_legend_handles_labels()
    uniq = dict(zip(labels, handles, strict=True))
    fig.legend(
        uniq.values(),
        uniq.keys(),
        loc="lower center",
        ncol=len(uniq),
        bbox_to_anchor=(0.5, -0.02 - 0.12 / max(1, len(subsets) / 3)),
    )
    name = f"by_{by}"
    _save(fig, out_dir, name)
    plt.close(fig)
    word = "scenario" if by == "scenario" else "kind of tool"
    return Figure(
        name,
        f"Results by {word}",
        f"Each dot is one situation's result for one {word}; bars are 95% intervals from the same grouped "
        "bootstrap as the headline results. Dashed lines are the headline lines (80% hits; 2× off). Small "
        f"groups have wide bars and are only indicative. Cases per dot: {_n_range(parts)}.",
    )


def _n_range(parts: list[dict]) -> str:
    ns = [p["n"] for p in parts if p.get("n")]
    return f"{min(ns)} to {max(ns)}" if ns else "none"


def fig_drift(results: dict, out_dir: Path) -> Figure | None:
    by_step = results.get("error_by_step") or {}
    if not any(by_step.values()):
        return None
    plt = _plt()
    fig, ax = plt.subplots(figsize=(6.4, 3.3))
    labels = [k for k, v in by_step.items() if v]
    for k, label in enumerate(labels):
        color, marker = SERIES[k]
        rows = by_step[label]
        x = np.array([r["step"] + 1 for r in rows], dtype=float) + (k - (len(labels) - 1) / 2) * 0.15
        est = np.array([100 * r["estimate"] for r in rows])
        lo = np.array([100 * r["low"] for r in rows])
        hi = np.array([100 * r["high"] for r in rows])
        ax.errorbar(
            x,
            est,
            yerr=[est - lo, hi - est],
            fmt=marker + "-",
            color=color,
            ms=6,
            lw=2,
            elinewidth=1.4,
            capsize=3,
            label=label,
        )
    ax.set_xlabel("Step in the chain (1 = answered with the real past)")
    ax.set_ylabel("Steps with a key fact wrong (%)")
    ax.set_ylim(0, 100)
    ax.set_xticks(range(1, 1 + max(r["step"] for v in by_step.values() for r in v) + 1))
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left")
    ax.set_title("Errors along the several-step chains")
    _save(fig, out_dir, "drift")
    plt.close(fig)
    n = sum(r["n"] for r in by_step.get("calls that matter", []))
    chains = max((r["n_clusters"] for v in by_step.values() for r in v), default=0)
    return Figure(
        "drift",
        "Drift along the chains",
        "Share of steps where the auditor got a key fact wrong, at each step of the chains. Bars are 95% "
        f"intervals with whole chains redrawn together. Calls that matter: {n} steps; up to {chains} chains "
        "per step.",
    )


PAIRED_GROUPS = [
    ("own past against real past", "Real past − own past\n(several steps)"),
    ("record of the others", "With − without the record\n(shared tool)"),
    ("long history", "Long − short history\n(one step)"),
]


def fig_paired(results: dict, out_dir: Path) -> Figure | None:
    parts = {(p["group"], p["subset"]): p for p in results["parts"] if p["group"] in dict(PAIRED_GROUPS)}
    if not parts:
        return None
    plt = _plt()
    present = [(g, lab) for g, lab in PAIRED_GROUPS if any(k[0] == g for k in parts)]
    fig, axes = plt.subplots(
        1, 2, figsize=(9.2, 0.75 * len(present) + 1.4), gridspec_kw={"wspace": 0.3}, sharey=True
    )
    ns = []
    for ax, subset in zip(axes, ("output", "timing"), strict=True):
        for i, (g, _) in enumerate(present):
            p = parts.get((g, subset))
            y = len(present) - 1 - i
            color, marker = SERIES[0]
            if not p or p.get("estimate") is None:
                continue
            ns.append(p.get("n"))
            if subset == "output":
                est, lo, hi = 100 * p["estimate"], 100 * p["low"], 100 * p["high"]
            else:
                est, lo, hi = _exp(p["estimate"]), _exp(p["low"]), _exp(p["high"])
            ax.errorbar(
                est, y, xerr=_err(est, lo, hi), fmt=marker, color=color, ms=7, elinewidth=2, capsize=4
            )
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        if subset == "output":
            ax.axvline(0, color=LINE, lw=1.1)
            ax.set_xlabel("Difference in hits (percentage points)")
            ax.set_title("Output")
        else:
            ax.set_xscale("log")
            ax.axvline(1, color=LINE, lw=1.1)
            ax.set_xlabel("Ratio of timing errors (log scale; above 1: first is further off)")
            ax.set_title("Timing")
            _log_ticks(ax)
    axes[0].set_yticks(range(len(present)))
    axes[0].set_yticklabels([lab for _, lab in reversed(present)])
    axes[0].set_ylim(-0.6, len(present) - 0.4)
    _save(fig, out_dir, "paired")
    plt.close(fig)
    return Figure(
        "paired",
        "Same commands, two ways",
        "Each row asks the auditor the same commands two ways and shows the difference. Output: difference "
        "in the share of hits. Timing: the typical ratio of the two timing errors. Bars are 95% intervals "
        f"from the grouped bootstrap. Pairs per row: {min(ns) if ns else 0} to {max(ns) if ns else 0}.",
    )


def fig_scatter(scores: pd.DataFrame, out_dir: Path, yardstick: pd.DataFrame | None) -> Figure | None:
    plt = _plt()
    panels = []
    for situation in an.SITUATIONS:
        df = an.headline_rows(scores, situation, "timing")
        if "predicted_seconds" not in df.columns:
            df = df.assign(predicted_seconds=np.exp(df["log_ratio"]) * df["real_seconds"])
        panels.append((situation, df))
    if not any(len(df) for _, df in panels):
        return None
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6), sharex=True, sharey=True, gridspec_kw={"wspace": 0.12})
    lo, hi = 1.0, 10.0
    dropped = 0
    rule_n = 0
    for _, df in panels:
        if len(df):
            hi = max(
                hi,
                float(df["real_seconds"].max()),
                float(df["predicted_seconds"].replace(np.inf, np.nan).max()),
            )
    hi *= 1.5
    for ax, (situation, df) in zip(axes, panels, strict=True):
        x = np.maximum(df["real_seconds"].astype(float), 1.0)
        y = df["predicted_seconds"].astype(float)
        ok = np.isfinite(y)
        dropped += int((~ok).sum())
        ax.plot([lo, hi], [lo, hi], color=LINE, lw=1)
        ax.plot([lo, hi], [2 * lo, 2 * hi], color=LINE, lw=0.9, ls="--")
        ax.plot([lo, hi], [lo / 2, hi / 2], color=LINE, lw=0.9, ls="--")
        ax.scatter(
            x[ok],
            np.maximum(y[ok], 1.0),
            s=16,
            color=SERIES[0][0],
            marker="o",
            alpha=0.65,
            edgecolors="white",
            linewidths=0.4,
            label="auditor",
        )
        if yardstick is not None and len(df):
            m = df[["key", "real_seconds"]].merge(yardstick[["key", "rule_seconds"]].dropna(), on="key")
            rule_n += len(m)
            ax.scatter(
                np.maximum(m["real_seconds"], 1.0),
                np.maximum(m["rule_seconds"], 1.0),
                s=18,
                color=SERIES[1][0],
                marker="x",
                linewidths=1.1,
                label="rule of thumb",
            )
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_title(an.SITUATION_NAMES[situation])
        ax.set_xlabel("Real time (s)")
        _log_seconds(ax)
        ax.grid(color=GRID, lw=0.6)
        ax.set_axisbelow(True)
    axes[0].set_ylabel("Predicted time (s)")
    axes[0].legend(loc="upper left")
    _save(fig, out_dir, "timing_scatter")
    plt.close(fig)
    n = sum(len(df) for _, df in panels)
    return Figure(
        "timing_scatter",
        "Predicted against real duration",
        f"Each dot is one command that matters and really finished ({n} in all). Solid line: exactly right; "
        "dashed lines: 2× too fast or too slow. Times under one second are shown at one second."
        + (f" Crosses: the rule of thumb on the same commands ({rule_n})." if rule_n else "")
        + (
            f" Not shown: {dropped} answers with no usable time (counted as infinitely wrong)."
            if dropped
            else ""
        ),
    )


def fig_queue(queue: pd.DataFrame | None, out_dir: Path) -> Figure | None:
    if queue is None or not len(queue) or "real_typical_wait_s" not in queue.columns:
        return None
    q = queue[queue.get("split", pd.Series("test", index=queue.index)).fillna("test") == "test"]
    q = q[q["real_typical_wait_s"].notna() & q["real_waiting_10min"].notna()]
    if q.empty:  # the real values are not filled in yet
        return None
    for col in ("typical_wait_s", "sim_typical_wait_s", "waiting_10min", "sim_waiting_10min"):
        if col in q.columns and q[col].isna().all():
            q = q.drop(columns=col)
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6), gridspec_kw={"wspace": 0.3})
    series = [("auditor", "", SERIES[0]), ("checker program", "sim_", SERIES[1])]
    ax = axes[0]
    real = np.maximum(q["real_typical_wait_s"].astype(float), 1.0)
    hi = float(real.max()) * 2 if len(real) else 100.0
    for label, prefix, (color, marker) in series:
        col = f"{prefix}typical_wait_s"
        if col in q.columns:
            pred = np.maximum(q[col].astype(float), 1.0)
            hi = max(hi, float(pred.max()) * 1.5)
            ax.scatter(
                real,
                pred,
                s=22,
                color=color,
                marker=marker,
                alpha=0.75,
                edgecolors="white",
                linewidths=0.4,
                label=label,
            )
    ax.plot([1, hi], [1, hi], color=LINE, lw=1)
    ax.plot([1, hi], [2, 2 * hi], color=LINE, lw=0.9, ls="--")
    ax.plot([1, hi], [0.5, hi / 2], color=LINE, lw=0.9, ls="--")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(1, hi)
    ax.set_ylim(1, hi)
    _log_seconds(ax)
    ax.set_xlabel("Real typical wait over the next 10 minutes (s)")
    ax.set_ylabel("Forecast (s)")
    ax.set_title("Typical wait")
    ax.legend(loc="upper left")
    ax = axes[1]
    real = q["real_waiting_10min"].astype(float)
    top = float(real.max()) if len(real) else 1.0
    for label, prefix, (color, marker) in series:
        col = f"{prefix}waiting_10min"
        if col in q.columns:
            pred = q[col].astype(float)
            top = max(top, float(pred.max()))
            ax.scatter(
                real,
                pred,
                s=22,
                color=color,
                marker=marker,
                alpha=0.75,
                edgecolors="white",
                linewidths=0.4,
                label=label,
            )
    top = top * 1.1 + 1
    ax.plot([0, top], [0, top], color=LINE, lw=1)
    ax.set_xlim(-0.5, top)
    ax.set_ylim(-0.5, top)
    from matplotlib.ticker import MaxNLocator

    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_xlabel("Real number of checks waiting, 10 minutes later")
    ax.set_ylabel("Forecast")
    ax.set_title("Line length in 10 minutes")
    for a in axes:
        a.grid(color=GRID, lw=0.6)
        a.set_axisbelow(True)
    _save(fig, out_dir, "queue")
    plt.close(fig)
    return Figure(
        "queue",
        "Waiting-line forecasts",
        f"Each dot is one frozen moment of a real run ({len(q)} moments), forecast by the auditor (dots) and "
        "by the program that follows the proof checker's rules (squares). Solid line: exactly right; dashed: "
        "2× off.",
    )


def make_figures(results, scores, out_dir: Path, *, yardstick=None, queue=None) -> list[Figure]:
    out_dir.mkdir(parents=True, exist_ok=True)
    figs = [
        fig_headline(results, out_dir),
        fig_subsets(results, out_dir, "scenario"),
        fig_subsets(results, out_dir, "tool_kind"),
        fig_drift(results, out_dir),
        fig_paired(results, out_dir),
        fig_scatter(scores, out_dir, yardstick),
        fig_queue(queue, out_dir),
    ]
    return [f for f in figs if f is not None]


# ---- Markdown -----------------------------------------------------------------------------------------------


def _figure_md(figs: dict[str, Figure], name: str) -> str:
    f = figs.get(name)
    if not f:
        return ""
    return f"![{f.title}]({f.name}.png)\n\n*Figure: {f.title}. {f.caption}*\n\n"


GROUP_ORDER = [
    ("by scenario", "By scenario"),
    ("by tool kind", "By kind of tool"),
    ("verdicts", "Pass-or-fail verdicts"),
    ("false passes", "False passes"),
    ("time band", "Right time band"),
    ("timing bias", "Too fast or too slow?"),
    ("timing sensitivity", "Timing with commands that shared a turn"),
    ("waiting", "Will it wait?"),
    ("drift", "Drift along the chains"),
    ("self-contradiction", "Self-contradiction"),
    ("own past against real past", "Own past against real past"),
    ("record of the others", "With and without the record of the others"),
    ("long history", "Long history"),
    ("rule of thumb", "The auditor against the rule of thumb"),
    ("waiting-line forecasts", "Waiting-line forecasts"),
    ("calls that don't matter", "Calls that don't matter"),
    ("self-consistency", "Asked twice"),
]
GROUP_FIGURE = {
    "by scenario": "by_scenario",
    "by tool kind": "by_tool_kind",
    "drift": "drift",
    "own past against real past": "paired",
    "rule of thumb": "timing_scatter",
    "waiting-line forecasts": "queue",
}


def render_report(
    results: dict, figures: list[Figure], *, title: str = "Auditor prediction study: results"
) -> str:
    figs = {f.name: f for f in figures}
    st = results["settings"]
    hs = {(h["situation"], h["measure"]): h for h in results["headline"]}
    out = [f"# {title}\n"]
    out.append(
        "The **auditor** is an AI model (Claude Opus 5.5) that pretends to be the computer: shown an agent's "
        "command, it writes what the command would print and how long it would take. This report checks its "
        "answers against what really happened in recorded swarmbench runs, in three situations: **one step** "
        "(it sees the real history before the command), **several steps** (chains of 8 commands where it sees "
        "its own earlier answers instead of the real ones), and a **shared tool under load** (several agents "
        "using one thing at once, with a record of what the others did). Headline results count only **calls "
        "that matter**: commands whose result an agent is likely to act on.\n"
    )
    out.append("## The six headline results\n")
    out.append(
        "**Output** is a hit when every key fact of the real output (pass or fail, the error and where, key "
        "numbers and names) is right. Its line is 80% hits. **Timing** error is how many times too fast or too "
        "slow the predicted time was (times under a second count as one second); the typical (median) error's "
        "line is 2× off. A result **matches** when it is shown to be on the good side of its line, **doesn't "
        'match** when shown to be on the bad side, and is **can\'t tell** otherwise. "Shown" means a one-sided '
        "test, with the six tests corrected together (Holm's method) so the chance of any false alarm is 5%.\n"
    )
    out.append("| | " + " | ".join(an.SITUATION_NAMES[s] for s in an.SITUATIONS) + " |")
    out.append("|---|---|---|---|")
    for measure, label in (("output", "Output right?"), ("timing", "Timing right?")):
        out.append(
            f"| **{label}** | " + " | ".join(headline_cell(hs[(s, measure)]) for s in an.SITUATIONS) + " |"
        )
    out.append("")
    out.append(
        "Ranges are 95% intervals from a bootstrap that redraws related cases together "
        f"({SCHEME_TEXT[st['clustering']]}), {st['n_boot']:,} redraws, seed {st['seed']}.\n"
    )
    out.append(_figure_md(figs, "headline"))
    out.append("### Details of the headline tests\n")
    out.append(
        "| Result | Estimate | 95% interval | One-sided p (match / not) | Holm-adjusted p | Grouping widens variance by (output) |"
    )
    out.append("|---|---|---|---|---|---|")
    for h in results["headline"]:
        name = f"{an.SITUATION_NAMES[h['situation']]}, {h['measure']}"
        if h["n"] == 0:
            out.append(f"| {name} | no data | | | | |")
            continue
        if h["measure"] == "output":
            e, rng = pct(h["estimate"]), f"{pct(h['low'])} to {pct(h['high'])}"
        else:
            e = factor(h["factor"])
            rng = f"{factor(h['factor_low'])} to {factor(h['factor_high'])}"
            if h.get("order_low") is not None:
                rng += f" (order-statistic check: {factor(_exp(h['order_low']))} to {factor(_exp(h['order_high']))})"
        de = (
            "–"
            if h.get("design_effect") is None or h["measure"] != "output"
            else f"{h['design_effect']:.1f}×"
        )
        out.append(
            f"| {name} | {e} | {rng} | {h['p_match']:.4f} / {h['p_mismatch']:.4f} | {h['p_holm']:.4f} | {de} |"
        )
    out.append("")

    out.append("## How many cases were scored\n")
    out.append(
        "| Split | Situation | Variant | Drawn | Answered | Parsed | Calls that matter | Output scored | Timing scored |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|")
    for c in results["counts"]:
        out.append(
            f"| {c['split']} | {an.SITUATION_NAMES.get(c['situation'], c['situation'])} | "
            f"{VARIANT_NAMES.get(c['variant'], c['variant'])} | {c['drawn']} | {c['answered']} | {c['parsed']} | "
            f"{c['matters']} | {c['output_scorable']} | {c['timing_scorable']} |"
        )
    out.append(
        "\nA drawn case with no usable answer counts as a miss for output and as infinitely wrong for timing.\n"
    )

    out.append("## The parts\n")
    out.append(
        "These results are reported with ranges but are not headlines. Where a part has a test, its p-value is "
        "adjusted with the Benjamini-Hochberg method across all parts (expected share of false alarms 10%); "
        '"significant" means it passes that bar.\n'
    )
    by_group: dict[str, list[dict]] = {}
    for p in results["parts"]:
        by_group.setdefault(p["group"], []).append(p)
    shown_figs = set()
    for group, heading in GROUP_ORDER:
        if group not in by_group:
            continue
        out.append(f"### {heading}\n")
        fname = GROUP_FIGURE.get(group)
        if group in ("record of the others", "long history"):
            fname = "paired"
        if fname and fname not in shown_figs:
            out.append(_figure_md(figs, fname))
            shown_figs.add(fname)
        out.append("| Result | Estimate | 95% interval | Cases | Adjusted p |")
        out.append("|---|---|---|---|---|")
        for p in by_group[group]:
            est, rng = format_part_value(p)
            measure = (
                {"output": " (output)", "timing": " (timing)"}.get(p["measure"], "")
                if group.startswith("by ")
                else ""
            )
            out.append(
                f"| {p['name']}{measure} | {est} | {rng} | {p.get('n') or p.get('n_chains') or ''} | {_p_text(p)} |"
            )
        out.append("")
    if "queue" in figs and "queue" not in shown_figs:
        out.append("### Waiting-line forecasts\n")
        out.append(_figure_md(figs, "queue"))

    out.append("## How the numbers were made\n")
    out.append(
        "- **Ranges.** A bootstrap redraws the cases thousands of times to see how much each estimate moves. "
        f"Related cases are redrawn together ({SCHEME_TEXT[st['clustering']]}), so they are never treated as "
        "independent. The pre-registration explains why runs are redrawn too.\n"
        "- **Headline tests.** One-sided tests against the lines, in the direction the estimate points, from "
        "the same bootstrap; Holm's correction over the six.\n"
        "- **Typical timing error.** The median of |ln(predicted / real)|, with times under a second set to one "
        "second. Its range is checked against one built from ordered values that assumes no distribution.\n"
        "- **Paired comparisons.** McNemar's exact test for hits, the Wilcoxon signed-rank test for timing errors.\n"
        "- **Drift.** The change in error rate from the first half of each chain to the second, averaged over "
        "chains and tested by flipping the sign of whole chains; checked with a logistic regression on step "
        "number in which each chain has its own baseline.\n"
    )
    return "\n".join(out)


# ---- Building ------------------------------------------------------------------------------------------------


def _json_default(o):
    if isinstance(o, np.integer | np.floating):
        return o.item()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


def build_report(
    scores: pd.DataFrame,
    out_dir: Path,
    *,
    yardstick: pd.DataFrame | None = None,
    queue: pd.DataFrame | None = None,
    contradictions: pd.DataFrame | None = None,
    seed: int = an.SEED,
    n_boot: int = an.N_BOOT,
    title: str = "Auditor prediction study: results",
    figures: bool = True,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    results = an.run_analysis(
        scores, yardstick=yardstick, queue=queue, contradictions=contradictions, seed=seed, n_boot=n_boot
    )
    (out_dir / "analysis.json").write_text(json.dumps(results, indent=1, default=_json_default))
    figs = make_figures(results, scores, out_dir, yardstick=yardstick, queue=queue) if figures else []
    path = out_dir / "report.md"
    path.write_text(render_report(results, figs, title=title))
    return path


def simulated_inputs(seed: int = 7) -> dict:
    """Scores, a rule of thumb and queue forecasts from simulation, with a known truth: one step right 93%
    of the time and 1.4x off; several steps 62% and 3.5x; shared tool 80% and 2x."""
    from swarmbench.studies.auditor import simulation as sim

    scores = sim.simulate_scores(
        hit_rate={"one_step": 0.93, "chain": 0.62, "shared": 0.80},
        timing_factor={"one_step": 1.4, "chain": 3.5, "shared": 2.0},
        seed=seed,
    )
    rng = np.random.default_rng(seed)
    real = scores.drop_duplicates("key")[["key", "real_seconds"]]
    yard = pd.DataFrame(
        {"key": real["key"], "rule_seconds": real["real_seconds"] * np.exp(rng.normal(0, 0.5, len(real)))}
    )
    n = 40
    rw = np.exp(rng.normal(np.log(60), 1.2, n))
    rq = rng.poisson(6, n)
    queue = pd.DataFrame(
        {
            "case_id": [f"q{i}" for i in range(n)],
            "split": "test",
            "real_typical_wait_s": rw,
            "real_waiting_5min": rq,
            "real_waiting_10min": rq + rng.poisson(1, n),
            "real_hits_limit": rw > 200,
            "typical_wait_s": rw * np.exp(rng.normal(0, 1.2, n)),
            "waiting_5min": rng.poisson(4, n),
            "waiting_10min": rng.poisson(4, n),
            "hits_limit": rng.random(n) < 0.3,
            "sim_typical_wait_s": rw * np.exp(rng.normal(0, 0.4, n)),
            "sim_waiting_5min": rq,
            "sim_waiting_10min": rq + rng.poisson(1, n) - 1,
            "sim_hits_limit": rw > 180,
        }
    )
    return {"scores": scores, "yardstick": yard, "queue": queue}


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Build the auditor study's results report.")
    ap.add_argument("--batch", default="test")
    ap.add_argument("--study-dir", type=Path, default=sc.STUDY_DIR)
    ap.add_argument("--simulated", action="store_true", help="build from simulated data with a known truth")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--n-boot", type=int, default=an.N_BOOT)
    args = ap.parse_args(argv)
    if args.simulated:
        data = simulated_inputs()
        out = args.out or args.study_dir / "report_simulated"
        path = build_report(
            data["scores"],
            out,
            yardstick=data["yardstick"],
            queue=data["queue"],
            n_boot=args.n_boot,
            title="Auditor prediction study: results (SIMULATED DATA)",
        )
    else:
        data = sc.load_inputs(args.study_dir, args.batch)
        scores = sc.score_answers(data["cases"], data["answers"], data["commands"], data["labels"])
        queue = None
        if data["queue_cases"] is not None and data["queue_answers"] is not None:
            queue = data["queue_cases"].merge(data["queue_answers"], on="case_id", how="left")
        out = args.out or args.study_dir / f"report_{args.batch}"
        out.mkdir(parents=True, exist_ok=True)
        scores.to_parquet(out / "scores.parquet")
        contra = sc.contradiction_candidates(scores)
        contra.to_csv(out / "contradiction_candidates.csv", index=False)
        path = build_report(
            scores, out, yardstick=data["yardstick"], queue=queue, contradictions=contra, n_boot=args.n_boot
        )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
