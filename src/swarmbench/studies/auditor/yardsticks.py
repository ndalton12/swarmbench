"""Free timing yardsticks for the auditor prediction study (docs/research/auditor-prediction-plan.md,
"The yardsticks").

An auditor's timing error means something only next to what is achievable. This module builds two
comparison points from the commands table alone, with no model calls:

1. **How much real timing varies by itself.** Commands run more than once with the same text and
   the same output, in one run or across runs of a scenario, should take about the same time. The
   spread of their durations is the floor no predictor can beat. (``repeat_groups``,
   ``real_spread``.)
2. **The timing rule of thumb.** A command's predicted duration is the typical real duration of
   the same command, or of a similar one, in *other* runs, adjusted for how busy the machine was
   (how many of the other agents' commands were running when it started). Evaluated leaving one
   run out at a time, on calls with measured durations. (``rule_of_thumb``.)

The proof checker's own yardstick, a program following the checker's rules, is in ``queue_sim``.

**The error measure** is the plan's: how many times too fast or too slow, with times under one
second counted as one second (``times_off``; 1.0 is exact, 2.0 is a factor of two either way).
"Typical" is the median.

**Kinds of tool** come from ``labels.parquet`` (``tool_kind``: queue, others, slow, quick,
excluded); commands labelled ``excluded`` (a bare sleep or wait) are left out.

Usage::

    uv run python -m swarmbench.studies.auditor.yardsticks          # writes the outputs below
    uv run python -m swarmbench.studies.auditor.yardsticks --queue  # also the queue validation

Outputs, in ``runs/_studies/auditor/``:

- ``yardstick_timing.parquet``: ``key``, ``rule_seconds`` (the rule's prediction, null if it has
  none), ``rule_level`` (which match it used), ``rule_seconds_plain`` (the same without the
  busyness adjustment), ``load`` (other agents' commands running at the call), ``real_spread``
  (how many times off this command's duration is from its repeats', typically; null if it has no
  repeat).
- ``yardstick_repeats.parquet``: one row per pair of repeats (both keys, run ids, durations).
- ``yardstick_queue.parquet``: the queue program's per-check validation rows (``--queue``).
- ``yardstick_summary.json``: the figures reported to the lead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from swarmbench.studies.auditor.queue_sim import command_text, strip_heredocs, study_dir, times_off

FLOOR_S = 1.0
"""Durations under this count as this (the plan: an agent can't notice the difference)."""

COLUMNS = [
    "key", "run_id", "scenario", "harness", "agent", "function", "command", "output", "output_status",
    "t_call", "duration_s", "timing_source",
]

# --- normalising commands -------------------------------------------------------------------

_SPACES = re.compile(r"\s+")
_HEAVY = (
    "lean-check", "submit", "lake", "lean", "python", "python3", "pytest", "node", "npm", "npx", "cargo",
    "make", "go", "gcc", "g++", "javac", "java", "ruby", "perl", "bash", "sh", "uv", "pip", "git", "curl",
)


def family(scenario: str) -> str:
    """The scenario with variant suffixes removed (proof-conference-planted-pool15 ->
    proof-conference), so variants of one scenario count as one."""
    s = scenario or ""
    for pat in (r"-planted.*$", r"-native-tools$", r"-low-pressure$", r"-v\d+$", r"-\d+$"):
        s = re.sub(pat, "", s)
    return s


def exact_text(function: str, command: Any) -> str:
    """The command as run, with runs of whitespace collapsed."""
    text = command_text(command) if isinstance(command, str) else ""
    return f"{function}\x00{_SPACES.sub(' ', text).strip()}"


_ARG = re.compile(r"""^(?:['"].*['"]|.*[/.\d=].*)$""")


def shape(function: str, command: Any) -> str:
    """The command with file contents and arguments blanked: program names and flags stay, any
    argument holding a path, a dot, a digit, an ``=`` or quotes becomes ``<a>``."""
    text = strip_heredocs(command_text(command) if isinstance(command, str) else "")
    out = []
    for tok in text.split():
        if tok.startswith("-") and not _ARG.match(tok[1:] or "x"):
            out.append(tok)
        elif _ARG.match(tok):
            out.append("<a>")
        else:
            out.append(tok)
    return f"{function}\x00{' '.join(out)[:400]}"


_SEP = re.compile(r"&&|\|\||[;|\n]|\$\(")


def program(function: str, command: Any) -> str:
    """The main program a command runs: the first well-known heavy program in it (a checker,
    interpreter, build tool), else the first program; for non-shell tools, the tool name."""
    text = strip_heredocs(command_text(command) if isinstance(command, str) else "")
    if not text or text.startswith("{"):
        return f"{function}\x00"
    progs = []
    for seg in _SEP.split(text):
        words = seg.strip().split()
        while words and (re.match(r"^\w+=", words[0]) or words[0] in ("sudo", "time", "nohup", "env", "exec", "timeout")):
            words = words[1:]
            if words and re.match(r"^\d+[smh]?$", words[0]):
                words = words[1:]
        if words:
            progs.append(words[0].rsplit("/", 1)[-1])
    for p in progs:
        if p in _HEAVY or p.startswith("python"):
            return f"{function}\x00{p}"
    return f"{function}\x00{progs[0] if progs else ''}"


def output_hash(output: Any) -> str | None:
    if not isinstance(output, str):
        return None
    text = "\n".join(line.rstrip() for line in output.strip().splitlines())
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --- loading --------------------------------------------------------------------------------


def load_table(commands_path: Path | None = None, labels_path: Path | None = None,
               data_dir: Path | None = None) -> pd.DataFrame:
    """The commands table with what the yardsticks need: kind of tool, keys for matching, the
    output's hash (the output itself is dropped to save memory), and the start time in seconds.
    A table with its own ``family`` column (SWE-bench: the project) keeps it."""
    import pyarrow.parquet as pq

    d = data_dir or study_dir()
    cpath = commands_path or d / "commands.parquet"
    has_family = "family" in pq.read_schema(cpath).names
    df = pd.read_parquet(cpath, columns=COLUMNS + (["family"] if has_family else []))
    df["out_hash"] = df["output"].map(output_hash)
    df = df.drop(columns=["output"])
    lp = labels_path or d / "labels.parquet"
    if lp.exists():
        lab = pd.read_parquet(lp, columns=["key", "tool_kind", "shared_thing", "matters"])
        df = df.merge(lab, on="key", how="left")
    else:
        df["tool_kind"] = None
        df["shared_thing"] = None
        df["matters"] = None
    df["matters"] = df["matters"].fillna(False).astype(bool)
    df["tool_kind"] = df["tool_kind"].fillna("unlabelled")
    derived = df["scenario"].map(family)
    df["family"] = df["family"].where(df["family"].notna(), derived) if has_family else derived
    df["k_exact"] = [exact_text(f, c) for f, c in zip(df["function"], df["command"])]
    df["k_shape"] = [shape(f, c) for f, c in zip(df["function"], df["command"])]
    df["k_prog"] = [program(f, c) for f, c in zip(df["function"], df["command"])]
    df["t0"] = df["t_call"].map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    df = df.drop(columns=["command"])
    df["measured"] = (
        df["duration_s"].notna() & (df["output_status"] != "missing") & (df["tool_kind"] != "excluded")
        # a SWE-bench reply's total over several commands run one after another is no one command's time
        & (df["timing_source"] != "turn_total")
    )
    return df


def add_load(df: pd.DataFrame) -> pd.DataFrame:
    """``load``: how many other agents' commands (with known durations) were running when each
    command was called, in the same run."""
    df = df.copy()
    df["load"] = np.nan
    for _, g in df.groupby("run_id"):
        ok = g[g["duration_s"].notna() & g["t0"].notna()]
        starts = ok["t0"].to_numpy()
        ends = starts + ok["duration_s"].to_numpy()
        agents = ok["agent"].to_numpy()
        s_all, e_all = np.sort(starts), np.sort(ends)
        per_agent = {
            a: (np.sort(starts[agents == a]), np.sort(ends[agents == a])) for a in np.unique(agents)
        }
        idx, loads = [], []
        for i, t, a in zip(g.index, g["t0"], g["agent"]):
            if np.isnan(t):
                continue
            tot = np.searchsorted(s_all, t, "left") - np.searchsorted(e_all, t, "right")
            sa, ea = per_agent.get(a, (np.array([]), np.array([])))
            mine = np.searchsorted(sa, t, "left") - np.searchsorted(ea, t, "right")
            idx.append(i)
            loads.append(max(0, int(tot - mine)))
        df.loc[idx, "load"] = loads
    return df


# --- 1. how much real timing varies ---------------------------------------------------------


def _log(x: np.ndarray | float) -> np.ndarray | float:
    return np.log(np.maximum(x, FLOOR_S))


def repeat_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Pairs of repeats: two measured calls of one scenario family with the same command text and
    the same output. One row per pair, with ``off`` = how many times apart their durations are."""
    m = df[df["measured"] & df["out_hash"].notna()]
    rows = []
    for (fam, kx, oh), g in m.groupby(["family", "k_exact", "out_hash"], sort=False):
        if len(g) < 2:
            continue
        if len(g) > 60:  # very common commands: a fixed sample keeps the pair count sane
            g = g.sample(60, random_state=0)
        keys, runs, durs = g["key"].to_numpy(), g["run_id"].to_numpy(), g["duration_s"].to_numpy()
        kinds = g["tool_kind"].to_numpy()
        matters = g["matters"].to_numpy()
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                rows.append(
                    {
                        "family": fam,
                        "group": hashlib.sha256((fam + kx + oh).encode()).hexdigest()[:12],
                        "key_a": keys[i],
                        "key_b": keys[j],
                        "run_a": runs[i],
                        "run_b": runs[j],
                        "dur_a": durs[i],
                        "dur_b": durs[j],
                        "tool_kind": kinds[i],
                        "same_run": runs[i] == runs[j],
                        "matters": bool(matters[i] and matters[j]),
                        "off": float(math.exp(abs(_log(durs[i]) - _log(durs[j])))),
                    }
                )
    return pd.DataFrame(rows)


def real_spread(pairs: pd.DataFrame) -> pd.Series:
    """For each command with repeats: the typical (median) times off from its repeats."""
    if pairs.empty:
        return pd.Series(dtype=float)
    long = pd.concat(
        [pairs[["key_a", "off"]].rename(columns={"key_a": "key"}), pairs[["key_b", "off"]].rename(columns={"key_b": "key"})]
    )
    return long.groupby("key")["off"].median()


def summarise_repeats(pairs: pd.DataFrame) -> dict[str, Any]:
    """Typical times off between repeats, overall and per kind of tool, within one run and across
    runs. Each group of repeats counts once (its median), so very common commands don't dominate."""
    if pairs.empty:
        return {}

    def block(p: pd.DataFrame) -> dict[str, Any]:
        per_group = p.groupby("group")["off"].median()
        return {
            "groups": len(per_group),
            "pairs": len(p),
            "typical_off": float(per_group.median()),
            "share_groups_within_2": float((per_group <= 2).mean()),
            "p90_off": float(per_group.quantile(0.9)),
        }

    out: dict[str, Any] = {"all": block(pairs)}
    if "matters" in pairs:
        both = pairs[pairs["matters"]]
        out["calls_that_matter"] = block(both) if len(both) else None
    out["within_run"] = block(pairs[pairs["same_run"]]) if pairs["same_run"].any() else None
    out["across_runs"] = block(pairs[~pairs["same_run"]]) if (~pairs["same_run"]).any() else None
    out["by_kind"] = {k: block(g) for k, g in pairs.groupby("tool_kind")}
    out["by_family"] = {k: block(g) for k, g in pairs.groupby("family")}
    return out


# --- 2. the timing rule of thumb ------------------------------------------------------------

LEVELS = [
    ("exact", ["family", "k_exact"], 1),
    ("shape", ["family", "k_shape"], 3),
    ("program", ["family", "k_prog"], 3),
    ("kind", ["family", "tool_kind"], 3),
    ("kind_any_scenario", ["tool_kind"], 3),
]
"""Matching levels, most specific first: (name, columns, the fewest matches it needs)."""


def _fit_slopes(train: pd.DataFrame) -> dict[str, float]:
    """Per kind of tool: how much log duration rises with log(1 + load), within groups of the same
    command shape (so different commands don't masquerade as load). Least squares, at least 0."""
    t = train[train["measured"] & train["load"].notna()].copy()
    t["y"] = _log(t["duration_s"].to_numpy())
    t["x"] = np.log1p(t["load"].to_numpy())
    slopes = {}
    for kind, g in t.groupby("tool_kind"):
        gm = g.groupby(["family", "k_shape"])
        dy = g["y"] - gm["y"].transform("mean")
        dx = g["x"] - gm["x"].transform("mean")
        den = float((dx * dx).sum())
        slopes[kind] = max(0.0, float((dx * dy).sum()) / den) if den > 1e-9 else 0.0
    return slopes


def rule_of_thumb(df: pd.DataFrame, adjust: bool = True, runs: set[str] | None = None) -> pd.DataFrame:
    """Leave-one-run-out predictions for every measured command (of ``runs`` only, when given; every
    run's commands still serve as training data for the others).

    For each run, everything is learned from the other runs only: for the most specific level of
    ``LEVELS`` with enough matches there, the prediction is the median of the matches' log
    durations, plus (with ``adjust``) the kind's slope times (log(1 + load) minus the matches'
    median log(1 + load)).
    """
    d = df[df["measured"]].copy()
    d["y"] = _log(d["duration_s"].to_numpy())
    d["x"] = np.log1p(d["load"].fillna(0).to_numpy())
    out = []
    for run, test in d.groupby("run_id"):
        if runs is not None and run not in runs:
            continue
        train = d[d["run_id"] != run]
        slopes = _fit_slopes(train) if adjust else {}
        pred = pd.Series(np.nan, index=test.index)
        plain = pd.Series(np.nan, index=test.index)
        level = pd.Series(None, index=test.index, dtype=object)
        for name, cols, need in LEVELS:
            todo = pred.isna()
            if not todo.any():
                break
            stats = train.groupby(cols).agg(n=("y", "size"), y=("y", "median"), x=("x", "median"))
            stats = stats[stats["n"] >= need]
            if stats.empty:
                continue
            joined = test.loc[todo, cols].join(stats, on=cols)
            hit = joined["y"].notna()
            idx = joined.index[hit]
            if len(idx) == 0:
                continue
            base = joined.loc[hit, "y"].to_numpy(dtype=float)
            plain.loc[idx] = base
            k = np.array([slopes.get(kd, 0.0) for kd in test.loc[idx, "tool_kind"]], dtype=float)
            dx = test.loc[idx, "x"].to_numpy(dtype=float) - joined.loc[hit, "x"].to_numpy(dtype=float)
            pred.loc[idx] = base + k * dx
            level.loc[idx] = name
        out.append(
            pd.DataFrame(
                {
                    "key": test["key"],
                    "rule_seconds": np.exp(pred),
                    "rule_seconds_plain": np.exp(plain),
                    "rule_level": level,
                }
            )
        )
    return pd.concat(out) if out else pd.DataFrame(columns=["key", "rule_seconds", "rule_seconds_plain", "rule_level"])


def summarise_rule(df: pd.DataFrame, pred: pd.DataFrame) -> dict[str, Any]:
    """Typical times off of the rule (and the unadjusted rule), overall and per kind, scenario and
    level, over measured commands it predicts."""
    m = df[df["measured"]][["key", "duration_s", "tool_kind", "family", "harness", "matters"]].merge(pred, on="key")
    m = m[m["rule_seconds"].notna()]
    m["off"] = [times_off(p, r) for p, r in zip(m["rule_seconds"], m["duration_s"])]
    m["off_plain"] = [times_off(p, r) for p, r in zip(m["rule_seconds_plain"], m["duration_s"])]

    def block(g: pd.DataFrame) -> dict[str, Any]:
        return {
            "n": len(g),
            "typical_off": float(g["off"].median()),
            "typical_off_unadjusted": float(g["off_plain"].median()),
            "share_within_2": float((g["off"] <= 2).mean()),
            "share_within_2_unadjusted": float((g["off_plain"] <= 2).mean()),
        }

    n_measured = int(df["measured"].sum())
    return {
        "measured_commands": n_measured,
        "predicted": len(m),
        "all": block(m),
        "calls_that_matter": block(m[m["matters"]]),
        "calls_that_matter_by_kind": {k: block(g) for k, g in m[m["matters"]].groupby("tool_kind")},
        "by_kind": {k: block(g) for k, g in m.groupby("tool_kind")},
        "by_family": {k: block(g) for k, g in m.groupby("family")},
        "by_level": {k: block(g) for k, g in m.groupby("rule_level")},
        "by_harness": {k: block(g) for k, g in m.groupby("harness")},
    }


# --- the queue program's validation ---------------------------------------------------------


def queue_validation() -> tuple[pd.DataFrame, dict[str, Any]]:
    """The queue program driven by every proof run's real checks, plain and calibrated."""
    from swarmbench.studies.auditor import queue_sim as q

    rows, summary = [], {}
    for rid in q.proof_run_ids():
        rq = q.load_run(rid)
        summary[rid] = {"slots": rq.slots.slots, "slots_how": rq.slots.how}
        for cal in (False, True):
            r = q.validate_run(rq.checks, rq.slots.slots, rq.run_end, calibrate=cal)
            summary[rid]["calibrated" if cal else "plain"] = q.summarise_validation(r)
            for x in r:
                x["run_id"] = rid
                x["calibrated"] = cal
            rows.extend(r)
    return pd.DataFrame(rows), summary


# --- command line ---------------------------------------------------------------------------


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(float(o)) else round(float(o), 3)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--queue", action="store_true", help="also validate the proof-checker queue program")
    ap.add_argument("--data", type=Path, default=None,
                    help="the study folder to read and write (default: runs/_studies/auditor)")
    ap.add_argument("--extra-commands", default=None,
                    help="another commands table in that folder whose runs only serve as training data for the "
                         "rule of thumb (SWE-bench: commands_extra.parquet); needs --extra-labels")
    ap.add_argument("--extra-labels", default=None, help="the labels of --extra-commands (labels_extra.parquet)")
    args = ap.parse_args(argv)
    out = args.data or study_dir()
    df = load_table(data_dir=out)
    own_runs = set(df["run_id"])
    if args.extra_commands:
        extra = load_table(out / args.extra_commands, out / (args.extra_labels or "labels_extra.parquet"), data_dir=out)
        df = pd.concat([df, extra[~extra["run_id"].isin(own_runs)]], ignore_index=True)
    df = add_load(df)
    pred = rule_of_thumb(df, runs=own_runs)  # extra runs: training data for the rule only
    df = df[df["run_id"].isin(own_runs)]
    pairs = repeat_groups(df)
    spread = real_spread(pairs)
    timing = df[["key", "load"]].merge(pred, on="key", how="left")
    timing["real_spread"] = timing["key"].map(spread)
    timing[["key", "rule_seconds", "rule_level", "rule_seconds_plain", "load", "real_spread"]].to_parquet(
        out / "yardstick_timing.parquet", index=False
    )
    pairs.to_parquet(out / "yardstick_repeats.parquet", index=False)
    summary: dict[str, Any] = {"repeats": summarise_repeats(pairs), "rule_of_thumb": summarise_rule(df, pred)}
    if args.queue:
        qrows, qsum = queue_validation()
        qrows.to_parquet(out / "yardstick_queue.parquet", index=False)
        summary["queue"] = qsum
    (out / "yardstick_summary.json").write_text(json.dumps(_clean(summary), indent=1))
    print(json.dumps(_clean({k: v for k, v in summary.items() if k != "queue"}), indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
